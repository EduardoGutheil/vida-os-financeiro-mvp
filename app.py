
import io
import re
import urllib.parse
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Vida OS Financeiro MVP v4", page_icon="💸", layout="wide")

DEFAULT_CATEGORIES = [
    "Moradia",
    "Supermercado",
    "Alimentação Fora de Casa",
    "Transporte",
    "Saúde",
    "Pets",
    "Assinaturas",
    "Lazer",
    "Compras Pessoais",
    "Seguros",
    "Encargos Financeiros",
    "Outros",
    "Pendente de Aprovação",
    "Excluir do Resumo",
]

BASE_DIR = Path(__file__).parent
DEFAULT_RULES = pd.read_excel(BASE_DIR / "regras_padrao_v4.xlsx")

def normalize_text(text: str) -> str:
    if pd.isna(text):
        return ""
    text = str(text).strip().upper()
    text = re.sub(r"PARCELA\s+\d+/\d+", "", text)
    text = re.sub(r"[*#_/\\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def detect_columns(df: pd.DataFrame):
    cols = {c.lower().strip(): c for c in df.columns}
    date_col = next((cols[c] for c in cols if c in {"date", "data"}), None)
    desc_col = next((cols[c] for c in cols if c in {"title", "descricao", "descrição", "historico", "histórico", "descricao_original"}), None)
    value_col = next((cols[c] for c in cols if c in {"amount", "valor"}), None)
    return date_col, desc_col, value_col

def read_statement(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        try:
            return pd.read_csv(uploaded_file)
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding="latin1")
    return pd.read_excel(uploaded_file)

def parse_amount(val):
    if pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace("R$", "").replace(" ", "")
    if "," in s and "." in s and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None

def merge_rules(system_rules: pd.DataFrame, user_rules: pd.DataFrame | None):
    base = system_rules.copy()
    if user_rules is None or user_rules.empty:
        return base.sort_values(["prioridade", "termo"]).reset_index(drop=True)
    cols = ["termo", "descricao_padrao", "categoria", "subcategoria", "prioridade", "ativo"]
    for col in cols:
        if col not in user_rules.columns:
            if col == "prioridade":
                user_rules[col] = 1
            elif col == "ativo":
                user_rules[col] = True
            else:
                user_rules[col] = ""
    merged = pd.concat([base[cols], user_rules[cols]], ignore_index=True)
    merged["ativo"] = merged["ativo"].fillna(True)
    merged["prioridade"] = merged["prioridade"].fillna(1)
    merged = merged.drop_duplicates(subset=["termo", "categoria", "subcategoria"], keep="last")
    return merged.sort_values(["prioridade", "termo"]).reset_index(drop=True)

def prepare_transactions(df: pd.DataFrame, origem: str) -> pd.DataFrame:
    date_col, desc_col, value_col = detect_columns(df)
    if not all([date_col, desc_col, value_col]):
        raise ValueError("Não consegui identificar colunas de data, descrição e valor.")
    out = df[[date_col, desc_col, value_col]].copy()
    out.columns = ["data", "descricao_original", "valor"]
    out["data"] = pd.to_datetime(out["data"], errors="coerce")
    out["valor"] = out["valor"].apply(parse_amount)
    out["descricao_padronizada"] = out["descricao_original"].apply(normalize_text)
    out["origem_importacao"] = origem
    if origem == "Cartão de Crédito":
        out["tipo"] = "Despesa"
    else:
        out["tipo"] = out["valor"].apply(lambda x: "Receita" if pd.notna(x) and x < 0 else "Despesa")
    out["categoria"] = ""
    out["subcategoria"] = ""
    out["status_classificacao"] = "Pendente"
    out["regra_aplicada"] = ""
    out["confianca"] = 0.0
    out["mes"] = out["data"].dt.month
    out["ano"] = out["data"].dt.year
    out = out.dropna(subset=["descricao_original", "valor"]).reset_index(drop=True)
    return out

def apply_rules(tx: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    tx = tx.copy()
    for idx, row in tx.iterrows():
        desc = str(row["descricao_padronizada"]).lower()
        for _, rule in rules.iterrows():
            termo = str(rule.get("termo", "")).strip().lower()
            if termo and termo in desc:
                tx.at[idx, "categoria"] = rule["categoria"]
                tx.at[idx, "subcategoria"] = rule.get("subcategoria", "")
                tx.at[idx, "regra_aplicada"] = termo
                tx.at[idx, "descricao_padronizada"] = rule.get("descricao_padrao", row["descricao_padronizada"])
                if rule["categoria"] == "Pendente de Aprovação":
                    tx.at[idx, "status_classificacao"] = "Pendente de Aprovação"
                    tx.at[idx, "confianca"] = 0.40
                elif rule["categoria"] == "Excluir do Resumo":
                    tx.at[idx, "status_classificacao"] = "Automática"
                    tx.at[idx, "confianca"] = 0.99
                else:
                    tx.at[idx, "status_classificacao"] = "Automática"
                    tx.at[idx, "confianca"] = 0.95
                break
    return tx

def add_manual_rules(existing_rules: pd.DataFrame, edited_rows: pd.DataFrame) -> pd.DataFrame:
    new_rules = []
    for _, row in edited_rows.iterrows():
        categoria = str(row.get("categoria", "")).strip()
        descricao = str(row.get("descricao_padronizada", "")).strip()
        if categoria and descricao:
            new_rules.append({
                "termo": descricao.lower(),
                "descricao_padrao": descricao.upper(),
                "categoria": categoria,
                "subcategoria": row.get("subcategoria", ""),
                "prioridade": 1,
                "ativo": True,
            })
    if not new_rules:
        return existing_rules
    appended = pd.concat([existing_rules, pd.DataFrame(new_rules)], ignore_index=True)
    return appended.drop_duplicates(subset=["termo", "categoria", "subcategoria"], keep="last").reset_index(drop=True)

def to_excel_bytes(sheets: dict) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, data in sheets.items():
            data.to_excel(writer, sheet_name=name[:31], index=False)
    buffer.seek(0)
    return buffer.read()

def build_google_search(text):
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(str(text))

st.title("💸 Vida OS Financeiro MVP v4")
st.caption("Importe o extrato, deixe o sistema classificar o máximo possível e ajuste apenas o que ficar pendente.")

if "user_rules" not in st.session_state:
    st.session_state.user_rules = pd.DataFrame(columns=["termo","descricao_padrao","categoria","subcategoria","prioridade","ativo"])
if "transactions" not in st.session_state:
    st.session_state.transactions = pd.DataFrame()
if "all_rules" not in st.session_state:
    st.session_state.all_rules = merge_rules(DEFAULT_RULES, st.session_state.user_rules)

with st.sidebar:
    st.subheader("Configuração")
    origem = st.selectbox("Tipo de importação", ["Cartão de Crédito", "Conta Corrente"], index=0)
    uploaded_rules = st.file_uploader("Opcional: importar regras do usuário", type=["csv", "xlsx"], key="rules")
    if uploaded_rules is not None:
        st.session_state.user_rules = pd.read_csv(uploaded_rules) if uploaded_rules.name.lower().endswith(".csv") else pd.read_excel(uploaded_rules)
        st.session_state.all_rules = merge_rules(DEFAULT_RULES, st.session_state.user_rules)
        st.success("Regras do usuário carregadas e mescladas com as regras padrão.")
    st.markdown("### Categorias")
    st.write(", ".join([c for c in DEFAULT_CATEGORIES if c != "Excluir do Resumo"]))

tab1, tab2, tab3, tab4 = st.tabs(["1. Importação", "2. Conciliação manual", "3. Dashboard", "4. Regras e exportação"])

with tab1:
    uploaded_file = st.file_uploader("Anexe o extrato bancário", type=["csv", "xlsx"], key="statement")
    process = st.button("Processar arquivo", type="primary", disabled=uploaded_file is None)
    if process and uploaded_file is not None:
        raw_df = read_statement(uploaded_file)
        tx = prepare_transactions(raw_df, origem=origem)
        tx = apply_rules(tx, st.session_state.all_rules)
        st.session_state.transactions = tx
        st.success(f"Arquivo processado com sucesso. {len(tx)} transações encontradas.")

    if not st.session_state.transactions.empty:
        tx = st.session_state.transactions.copy()
        dashboard_base = tx[~tx["categoria"].isin(["Excluir do Resumo"])].copy()
        dashboard_base = dashboard_base[dashboard_base["valor"] > 0].copy()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Transações", len(tx))
        c2.metric("Automáticas", int((tx["status_classificacao"] == "Automática").sum()))
        c3.metric("Pendentes", int((tx["status_classificacao"].isin(["Pendente", "Pendente de Aprovação"])).sum()))
        c4.metric("Despesas no dashboard", f"R$ {dashboard_base['valor'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        st.markdown("### Prévia das transações")
        st.dataframe(
            tx[["data","descricao_original","valor","descricao_padronizada","categoria","subcategoria","status_classificacao"]],
            use_container_width=True,
            height=360
        )

with tab2:
    if st.session_state.transactions.empty:
        st.info("Processe um extrato primeiro.")
    else:
        tx = st.session_state.transactions.copy()
        pend = tx[tx["status_classificacao"].isin(["Pendente", "Pendente de Aprovação"])].copy()
        if pend.empty:
            st.success("Nenhuma pendência para revisar.")
        else:
            st.markdown("### Ajuste só o que o sistema não conseguiu fechar sozinho")
            editor_df = pend[["data","descricao_original","descricao_padronizada","valor","categoria","subcategoria","status_classificacao"]].copy()
            editor_df["categoria"] = editor_df["categoria"].replace("", "Pendente de Aprovação")
            edited = st.data_editor(
                editor_df,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config={
                    "categoria": st.column_config.SelectboxColumn("categoria", options=DEFAULT_CATEGORIES, required=True),
                    "subcategoria": st.column_config.TextColumn("subcategoria"),
                    "status_classificacao": st.column_config.SelectboxColumn("status_classificacao", options=["Pendente", "Pendente de Aprovação", "Manual", "Automática"], disabled=True),
                },
                key="pending_editor"
            )

            if st.button("Salvar conciliação manual", type="primary"):
                tx2 = tx.copy()
                for _, row in edited.iterrows():
                    mask = (
                        (tx2["data"] == row["data"]) &
                        (tx2["descricao_original"] == row["descricao_original"]) &
                        (tx2["valor"] == row["valor"])
                    )
                    tx2.loc[mask, "descricao_padronizada"] = row["descricao_padronizada"]
                    tx2.loc[mask, "categoria"] = row["categoria"]
                    tx2.loc[mask, "subcategoria"] = row["subcategoria"]
                    tx2.loc[mask, "status_classificacao"] = "Manual"
                    tx2.loc[mask, "confianca"] = 1.0
                    tx2.loc[mask, "regra_aplicada"] = "ajuste_manual"

                new_manual_rows = tx2[tx2["status_classificacao"] == "Manual"][["descricao_padronizada","categoria","subcategoria"]].copy()
                st.session_state.user_rules = add_manual_rules(st.session_state.user_rules, new_manual_rows)
                st.session_state.all_rules = merge_rules(DEFAULT_RULES, st.session_state.user_rules)
                st.session_state.transactions = tx2
                st.success("Conciliação salva. As novas regras do usuário já foram adicionadas para as próximas importações.")

            st.markdown("### Pesquisa rápida para casos duvidosos")
            search_df = pend[["descricao_original"]].drop_duplicates().copy()
            search_df["google_search"] = search_df["descricao_original"].apply(build_google_search)
            st.dataframe(search_df, use_container_width=True, height=220)

with tab3:
    if st.session_state.transactions.empty:
        st.info("Processe um extrato para ver o dashboard.")
    else:
        tx = st.session_state.transactions.copy()
        despesas = tx[~tx["categoria"].isin(["Excluir do Resumo"])].copy()
        despesas = despesas[despesas["valor"] > 0].copy()

        col1, col2, col3 = st.columns(3)
        col1.metric("Total gasto analisado", f"R$ {despesas['valor'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        col2.metric("Categorias com gasto", despesas["categoria"].replace("", pd.NA).dropna().nunique())
        col3.metric("Taxa de automação", f"{round((tx['status_classificacao'] == 'Automática').mean() * 100, 1)}%")

        st.markdown("### Gastos por categoria")
        cat_summary = despesas.groupby("categoria", dropna=False)["valor"].sum().reset_index().sort_values("valor", ascending=False)
        st.bar_chart(cat_summary.set_index("categoria"))

        colA, colB = st.columns([1.1, 0.9])
        with colA:
            st.markdown("### Maiores gastos")
            top = despesas.sort_values("valor", ascending=False).head(15)
            st.dataframe(top[["data","descricao_original","categoria","subcategoria","valor"]], use_container_width=True, height=360)
        with colB:
            st.markdown("### Pendências restantes")
            pend_rest = tx[tx["status_classificacao"].isin(["Pendente", "Pendente de Aprovação"])][["descricao_original","valor","categoria","subcategoria","status_classificacao"]]
            st.dataframe(pend_rest, use_container_width=True, height=360)

with tab4:
    st.markdown("### Regras em uso")
    st.write(f"Regras padrão: {len(DEFAULT_RULES)} | Regras do usuário: {len(st.session_state.user_rules)} | Total: {len(st.session_state.all_rules)}")
    st.dataframe(st.session_state.all_rules, use_container_width=True, height=300)

    if not st.session_state.transactions.empty:
        export_xlsx = to_excel_bytes({
            "transacoes": st.session_state.transactions,
            "regras_usuario": st.session_state.user_rules,
            "regras_totais": st.session_state.all_rules,
        })
        st.download_button(
            "Baixar resultado completo",
            data=export_xlsx,
            file_name="vida_os_resultado_v4.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    rules_export = to_excel_bytes({
        "regras_usuario": st.session_state.user_rules if not st.session_state.user_rules.empty else pd.DataFrame(columns=["termo","descricao_padrao","categoria","subcategoria","prioridade","ativo"])
    })
    st.download_button(
        "Baixar regras do usuário",
        data=rules_export,
        file_name="regras_usuario_v4.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

st.divider()
st.caption("V4 focada em fluxo real: importar, classificar, editar pendências e reaproveitar regras nas próximas importações. Próximo passo natural: persistência com banco de dados.")
