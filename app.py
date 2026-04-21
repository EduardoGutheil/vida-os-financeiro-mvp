
import io
import re
from datetime import datetime

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Vida OS Financeiro MVP",
    page_icon="💸",
    layout="wide"
)

DEFAULT_CATEGORIES = [
    "Receitas",
    "Moradia",
    "Supermercado",
    "Alimentação Fora de Casa",
    "Transporte",
    "Saúde",
    "Pets",
    "Assinaturas",
    "Lazer",
    "Compras Pessoais",
    "Trabalho/Negócios",
    "Investimentos",
    "Transferências",
    "Impostos/Taxas",
    "Outros",
]

DEFAULT_RULES = pd.DataFrame(
    [
        {"termo": "google", "descricao_padrao": "GOOGLE", "categoria": "Assinaturas", "subcategoria": "Google", "prioridade": 1, "ativo": True},
        {"termo": "supermerc", "descricao_padrao": "SUPERMERCADO", "categoria": "Supermercado", "subcategoria": "Mercado", "prioridade": 1, "ativo": True},
        {"termo": "ifood", "descricao_padrao": "IFOOD", "categoria": "Alimentação Fora de Casa", "subcategoria": "Delivery", "prioridade": 1, "ativo": True},
        {"termo": "uber", "descricao_padrao": "UBER", "categoria": "Transporte", "subcategoria": "App", "prioridade": 1, "ativo": True},
        {"termo": "99", "descricao_padrao": "99", "categoria": "Transporte", "subcategoria": "App", "prioridade": 1, "ativo": True},
        {"termo": "farm", "descricao_padrao": "FARMACIA", "categoria": "Saúde", "subcategoria": "Farmácia", "prioridade": 1, "ativo": True},
        {"termo": "droga", "descricao_padrao": "FARMACIA", "categoria": "Saúde", "subcategoria": "Farmácia", "prioridade": 1, "ativo": True},
        {"termo": "pet", "descricao_padrao": "PETSHOP", "categoria": "Pets", "subcategoria": "Petshop", "prioridade": 1, "ativo": True},
        {"termo": "netflix", "descricao_padrao": "NETFLIX", "categoria": "Assinaturas", "subcategoria": "Streaming", "prioridade": 1, "ativo": True},
        {"termo": "spotify", "descricao_padrao": "SPOTIFY", "categoria": "Assinaturas", "subcategoria": "Streaming", "prioridade": 1, "ativo": True},
    ]
)

def normalize_text(text: str) -> str:
    if pd.isna(text):
        return ""
    text = str(text).strip().upper()
    text = re.sub(r"PARCELA\s+\d+/\d+", "", text)
    text = re.sub(r"\b\d{2,}\b", "", text)
    text = re.sub(r"[*#_/\\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def detect_columns(df: pd.DataFrame):
    cols = {c.lower().strip(): c for c in df.columns}
    date_col = next((cols[c] for c in cols if c in {"date", "data"}), None)
    desc_col = next((cols[c] for c in cols if c in {"title", "descricao", "descrição", "historico", "histórico"}), None)
    value_col = next((cols[c] for c in cols if c in {"amount", "valor"}), None)
    return date_col, desc_col, value_col

def read_statement(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        try:
            df = pd.read_csv(uploaded_file)
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, encoding="latin1")
    elif name.endswith(".xlsx"):
        df = pd.read_excel(uploaded_file)
    else:
        raise ValueError("Formato não suportado. Use CSV ou XLSX.")
    return df

def parse_amount(val):
    if pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    s = s.replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        # assume Brazilian format like 1.234,56
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None

def prepare_transactions(df: pd.DataFrame) -> pd.DataFrame:
    date_col, desc_col, value_col = detect_columns(df)
    if not all([date_col, desc_col, value_col]):
        raise ValueError(
            "Não consegui identificar as colunas. O arquivo precisa ter colunas equivalentes a data, descrição e valor."
        )
    out = df[[date_col, desc_col, value_col]].copy()
    out.columns = ["data", "descricao_original", "valor"]
    out["data"] = pd.to_datetime(out["data"], errors="coerce")
    out["valor"] = out["valor"].apply(parse_amount)
    out["descricao_padronizada"] = out["descricao_original"].apply(normalize_text)
    out["tipo"] = out["valor"].apply(lambda x: "Receita" if pd.notna(x) and x > 0 else "Despesa")
    out["categoria"] = ""
    out["subcategoria"] = ""
    out["status_classificacao"] = "Pendente"
    out["regra_aplicada"] = ""
    out["confianca"] = 0.0
    out["mes"] = out["data"].dt.month
    out["ano"] = out["data"].dt.year
    out = out.dropna(subset=["descricao_original", "valor"]).reset_index(drop=True)
    return out

def apply_rules(transacoes: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    tx = transacoes.copy()
    if rules.empty:
        return tx
    rules2 = rules.copy()
    if "ativo" in rules2.columns:
        rules2 = rules2[rules2["ativo"].astype(str).str.lower().isin(["true", "1", "sim"]) | (rules2["ativo"] == True)]
    if "prioridade" not in rules2.columns:
        rules2["prioridade"] = 999
    rules2 = rules2.sort_values(["prioridade", "termo"], ascending=[True, True])

    for idx, row in tx.iterrows():
        desc = str(row["descricao_padronizada"]).lower()
        for _, rule in rules2.iterrows():
            termo = str(rule.get("termo", "")).strip().lower()
            if termo and termo in desc:
                tx.at[idx, "categoria"] = rule.get("categoria", "Outros")
                tx.at[idx, "subcategoria"] = rule.get("subcategoria", "")
                tx.at[idx, "status_classificacao"] = "Automática"
                tx.at[idx, "regra_aplicada"] = termo
                tx.at[idx, "confianca"] = 0.95
                if rule.get("descricao_padrao"):
                    tx.at[idx, "descricao_padronizada"] = rule.get("descricao_padrao")
                break
    return tx

def add_manual_rules(original_rules: pd.DataFrame, edited_rows: pd.DataFrame) -> pd.DataFrame:
    new_rules = []
    for _, row in edited_rows.iterrows():
        if str(row.get("categoria", "")).strip() and str(row.get("status_classificacao", "")).strip() == "Manual":
            termo = str(row.get("descricao_padronizada", "")).strip().lower()
            if termo:
                new_rules.append({
                    "termo": termo,
                    "descricao_padrao": str(row.get("descricao_padronizada", "")).strip().upper(),
                    "categoria": row.get("categoria", "Outros"),
                    "subcategoria": row.get("subcategoria", ""),
                    "prioridade": 1,
                    "ativo": True,
                })
    if not new_rules:
        return original_rules.drop_duplicates().reset_index(drop=True)
    appended = pd.concat([original_rules, pd.DataFrame(new_rules)], ignore_index=True)
    appended = appended.drop_duplicates(subset=["termo", "categoria", "subcategoria"], keep="last").reset_index(drop=True)
    return appended

def to_excel_bytes(df_dict: dict) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, data in df_dict.items():
            data.to_excel(writer, sheet_name=name[:31], index=False)
    buffer.seek(0)
    return buffer.read()

st.title("💸 Vida OS Financeiro MVP")
st.caption("Faça upload do extrato, categorize automaticamente e ajuste apenas o que ficar pendente.")

if "rules" not in st.session_state:
    st.session_state.rules = DEFAULT_RULES.copy()

if "transactions" not in st.session_state:
    st.session_state.transactions = pd.DataFrame()

with st.sidebar:
    st.subheader("Configuração")
    uploaded_rules = st.file_uploader("Opcional: subir regras existentes", type=["csv", "xlsx"], key="rules_uploader")
    if uploaded_rules is not None:
        try:
            if uploaded_rules.name.lower().endswith(".csv"):
                st.session_state.rules = pd.read_csv(uploaded_rules)
            else:
                st.session_state.rules = pd.read_excel(uploaded_rules)
            st.success("Regras carregadas.")
        except Exception as e:
            st.error(f"Erro ao carregar regras: {e}")

    st.markdown("### Categorias padrão")
    st.write(", ".join(DEFAULT_CATEGORIES))

tab1, tab2, tab3 = st.tabs(["Upload e processamento", "Revisão manual", "Resumo"])

with tab1:
    uploaded_file = st.file_uploader("Anexe o extrato bancário", type=["csv", "xlsx"])
    process = st.button("Processar arquivo", type="primary", disabled=uploaded_file is None)

    if process and uploaded_file is not None:
        try:
            raw_df = read_statement(uploaded_file)
            tx = prepare_transactions(raw_df)
            tx = apply_rules(tx, st.session_state.rules)
            st.session_state.transactions = tx
            st.success(f"Arquivo processado com sucesso. {len(tx)} transações encontradas.")
        except Exception as e:
            st.error(f"Erro ao processar arquivo: {e}")

    if not st.session_state.transactions.empty:
        tx = st.session_state.transactions
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Transações", len(tx))
        c2.metric("Classificadas automaticamente", int((tx["status_classificacao"] == "Automática").sum()))
        c3.metric("Pendentes", int((tx["status_classificacao"] == "Pendente").sum()))
        c4.metric("Valor total", f"R$ {tx['valor'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        st.dataframe(tx, use_container_width=True, height=350)

        export_full = to_excel_bytes({
            "transacoes": tx,
            "regras": st.session_state.rules,
        })
        st.download_button(
            "Baixar resultado em Excel",
            data=export_full,
            file_name="resultado_financeiro.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

with tab2:
    if st.session_state.transactions.empty:
        st.info("Processe um extrato primeiro.")
    else:
        tx = st.session_state.transactions.copy()
        pending = tx[tx["status_classificacao"] != "Automática"].copy()

        if pending.empty:
            st.success("Tudo foi classificado automaticamente.")
        else:
            st.write("Ajuste apenas o que não foi classificado sozinho.")
            editable = pending[["data", "descricao_original", "descricao_padronizada", "valor", "categoria", "subcategoria"]].copy()
            editable["categoria"] = editable["categoria"].replace("", "Outros")
            edited = st.data_editor(
                editable,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    "categoria": st.column_config.SelectboxColumn(
                        "categoria",
                        options=DEFAULT_CATEGORIES,
                        required=True,
                    ),
                    "subcategoria": st.column_config.TextColumn("subcategoria"),
                },
                hide_index=True,
                key="editor"
            )

            if st.button("Salvar ajustes manuais"):
                tx2 = tx.copy()
                for _, row in edited.iterrows():
                    mask = (
                        (tx2["data"] == row["data"])
                        & (tx2["descricao_original"] == row["descricao_original"])
                        & (tx2["valor"] == row["valor"])
                    )
                    tx2.loc[mask, "descricao_padronizada"] = row["descricao_padronizada"]
                    tx2.loc[mask, "categoria"] = row["categoria"]
                    tx2.loc[mask, "subcategoria"] = row["subcategoria"]
                    tx2.loc[mask, "status_classificacao"] = "Manual"
                    tx2.loc[mask, "confianca"] = 1.0
                    tx2.loc[mask, "regra_aplicada"] = "ajuste_manual"

                st.session_state.transactions = tx2
                st.session_state.rules = add_manual_rules(st.session_state.rules, tx2[tx2["status_classificacao"] == "Manual"])
                st.success("Ajustes salvos e regras atualizadas.")

        rules_export = to_excel_bytes({"regras": st.session_state.rules})
        st.download_button(
            "Baixar regras atualizadas",
            data=rules_export,
            file_name="regras_atualizadas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        st.markdown("### Regras atuais")
        st.dataframe(st.session_state.rules, use_container_width=True, height=250)

with tab3:
    if st.session_state.transactions.empty:
        st.info("Processe um extrato para ver o resumo.")
    else:
        tx = st.session_state.transactions.copy()
        tx["mes_ref"] = tx["data"].dt.strftime("%Y-%m")
        despesas = tx[tx["valor"] > 0].copy()

        st.markdown("### Gastos por categoria")
        cat_summary = (
            despesas.groupby("categoria", dropna=False)["valor"]
            .sum()
            .reset_index()
            .sort_values("valor", ascending=False)
        )
        st.bar_chart(cat_summary.set_index("categoria"))

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### Top gastos")
            top = despesas.sort_values("valor", ascending=False).head(10)
            st.dataframe(top[["data", "descricao_original", "categoria", "valor"]], use_container_width=True, height=320)

        with col2:
            st.markdown("### Resumo por mês")
            month_summary = (
                despesas.groupby("mes_ref")["valor"]
                .sum()
                .reset_index()
                .sort_values("mes_ref")
            )
            st.line_chart(month_summary.set_index("mes_ref"))

st.divider()
st.caption("MVP para validação pessoal. Próxima evolução: login, banco de dados, histórico persistente e orçamento por categoria.")
