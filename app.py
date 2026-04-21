
import io
import re
import urllib.parse
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Vida OS Financeiro MVP", page_icon="💸", layout="wide")

DEFAULT_CATEGORIES = [
    "Receitas","Moradia","Supermercado","Alimentação Fora de Casa","Transporte","Saúde","Pets",
    "Assinaturas","Lazer","Compras Pessoais","Trabalho/Negócios","Investimentos","Transferências",
    "Impostos/Taxas","Encargos Financeiros","Outros","Pendente de Aprovação"
]

DEFAULT_RULES = pd.read_excel("regras_expandidas_financeiro.xlsx")

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
    desc_col = next((cols[c] for c in cols if c in {"title", "descricao", "descrição", "historico", "histórico"}), None)
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
    s = str(val).replace("R$", "").replace(" ", "")
    if "," in s and "." in s and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None

def prepare_transactions(df: pd.DataFrame, origem="Conta Corrente") -> pd.DataFrame:
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
        payment_mask = out["descricao_padronizada"].str.contains("PAGAMENTO RECEBIDO|ESTORNO|AJUSTE", na=False)
        out.loc[payment_mask, "tipo"] = "Transferência"
    else:
        out["tipo"] = out["valor"].apply(lambda x: "Receita" if pd.notna(x) and x < 0 else "Despesa")

    out["categoria"] = ""
    out["subcategoria"] = ""
    out["status_classificacao"] = "Pendente"
    out["regra_aplicada"] = ""
    out["confianca"] = 0.0
    out["mes"] = out["data"].dt.month
    out["ano"] = out["data"].dt.year
    return out.dropna(subset=["descricao_original", "valor"]).reset_index(drop=True)

def apply_rules(tx: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    tx = tx.copy()
    rules = rules.copy()
    rules = rules[rules["ativo"] == True].sort_values(["prioridade", "termo"])
    for idx, row in tx.iterrows():
        desc = str(row["descricao_padronizada"]).lower()
        for _, rule in rules.iterrows():
            termo = str(rule["termo"]).strip().lower()
            if termo and termo in desc:
                tx.at[idx, "categoria"] = rule["categoria"]
                tx.at[idx, "subcategoria"] = rule["subcategoria"]
                tx.at[idx, "status_classificacao"] = "Automática"
                tx.at[idx, "regra_aplicada"] = termo
                tx.at[idx, "confianca"] = 0.95 if rule["categoria"] != "Pendente de Aprovação" else 0.40
                tx.at[idx, "descricao_padronizada"] = rule["descricao_padrao"]
                if rule["categoria"] == "Pendente de Aprovação":
                    tx.at[idx, "status_classificacao"] = "Pendente de Aprovação"
                break
    return tx

def add_manual_rules(existing_rules: pd.DataFrame, edited_rows: pd.DataFrame) -> pd.DataFrame:
    new_rules = []
    for _, row in edited_rows.iterrows():
        if str(row.get("categoria", "")).strip():
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
    out = pd.concat([existing_rules, pd.DataFrame(new_rules)], ignore_index=True)
    return out.drop_duplicates(subset=["termo", "categoria", "subcategoria"], keep="last").reset_index(drop=True)

def to_excel_bytes(sheets: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    buf.seek(0)
    return buf.read()

st.title("💸 Vida OS Financeiro MVP")
st.caption("Upload do extrato, classificação automática reforçada e fila de pendente de aprovação.")

if "rules" not in st.session_state:
    st.session_state.rules = DEFAULT_RULES.copy()
if "transactions" not in st.session_state:
    st.session_state.transactions = pd.DataFrame()

with st.sidebar:
    st.subheader("Configuração")
    origem = st.selectbox("Tipo de importação", ["Cartão de Crédito", "Conta Corrente"], index=0)
    uploaded_rules = st.file_uploader("Opcional: subir regras existentes", type=["csv", "xlsx"])
    if uploaded_rules is not None:
        st.session_state.rules = pd.read_csv(uploaded_rules) if uploaded_rules.name.lower().endswith(".csv") else pd.read_excel(uploaded_rules)
        st.success("Regras carregadas.")
    st.write("Categorias:", ", ".join(DEFAULT_CATEGORIES))

tab1, tab2, tab3, tab4 = st.tabs(["Upload", "Revisão manual", "Pendentes de aprovação", "Resumo"])

with tab1:
    uploaded = st.file_uploader("Anexe o extrato bancário", type=["csv", "xlsx"], key="extrato")
    if st.button("Processar arquivo", type="primary", disabled=uploaded is None):
        raw = read_statement(uploaded)
        tx = prepare_transactions(raw, origem=origem)
        tx = apply_rules(tx, st.session_state.rules)
        st.session_state.transactions = tx
        st.success(f"Arquivo processado com sucesso. {len(tx)} transações encontradas.")
    if not st.session_state.transactions.empty:
        tx = st.session_state.transactions
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Transações", len(tx))
        c2.metric("Classificadas automaticamente", int((tx["status_classificacao"] == "Automática").sum()))
        c3.metric("Pendentes", int((tx["status_classificacao"].isin(["Pendente", "Pendente de Aprovação"])).sum()))
        c4.metric("Valor total", f"R$ {tx['valor'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        st.dataframe(tx, use_container_width=True, height=360)
        st.download_button(
            "Baixar resultado em Excel",
            data=to_excel_bytes({"transacoes": tx, "regras": st.session_state.rules}),
            file_name="resultado_financeiro.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

with tab2:
    if st.session_state.transactions.empty:
        st.info("Processe um extrato primeiro.")
    else:
        tx = st.session_state.transactions.copy()
        review = tx[tx["status_classificacao"].isin(["Pendente", "Pendente de Aprovação"])].copy()
        if review.empty:
            st.success("Nenhuma pendência para revisar.")
        else:
            edit = review[["data","descricao_original","descricao_padronizada","valor","categoria","subcategoria"]].copy()
            edit["categoria"] = edit["categoria"].replace("", "Outros")
            edited = st.data_editor(
                edit,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "categoria": st.column_config.SelectboxColumn("categoria", options=DEFAULT_CATEGORIES, required=True),
                    "subcategoria": st.column_config.TextColumn("subcategoria"),
                }
            )
            if st.button("Salvar ajustes manuais"):
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
                st.session_state.transactions = tx2
                st.session_state.rules = add_manual_rules(st.session_state.rules, tx2[tx2["status_classificacao"] == "Manual"])
                st.success("Ajustes salvos e regras atualizadas.")

with tab3:
    if st.session_state.transactions.empty:
        st.info("Processe um extrato primeiro.")
    else:
        pend = st.session_state.transactions[st.session_state.transactions["status_classificacao"].isin(["Pendente", "Pendente de Aprovação"])].copy()
        if pend.empty:
            st.success("Sem pendentes.")
        else:
            pend["google_search"] = pend["descricao_original"].apply(lambda x: "https://www.google.com/search?q=" + urllib.parse.quote_plus(str(x)))
            st.write("Use esta fila para casos em que o sistema precisa de confirmação.")
            st.dataframe(pend[["data","descricao_original","descricao_padronizada","valor","categoria","subcategoria","status_classificacao","google_search"]], use_container_width=True, height=360)

with tab4:
    if st.session_state.transactions.empty:
        st.info("Processe um extrato para ver o resumo.")
    else:
        tx = st.session_state.transactions.copy()
        despesas = tx[tx["tipo"].isin(["Despesa","Transferência"])].copy()
        st.markdown("### Gastos por categoria")
        resumo_cat = despesas.groupby("categoria", dropna=False)["valor"].sum().reset_index().sort_values("valor", ascending=False)
        st.bar_chart(resumo_cat.set_index("categoria"))
        st.markdown("### Top gastos")
        st.dataframe(despesas.sort_values("valor", ascending=False).head(15)[["data","descricao_original","categoria","subcategoria","valor"]], use_container_width=True)

st.caption("Próximo passo: persistir regras em banco e adicionar enriquecimento online controlado.")
