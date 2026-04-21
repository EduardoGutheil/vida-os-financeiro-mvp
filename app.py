
import io
import re
import urllib.parse
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Vida OS Financeiro MVP v3", page_icon="💸", layout="wide")

DEFAULT_CATEGORIES = [
    "Moradia","Supermercado","Alimentação Fora de Casa","Transporte","Saúde","Pets",
    "Assinaturas","Lazer","Compras Pessoais","Seguros","Encargos Financeiros","Outros","Pendente de Aprovação"
]

DEFAULT_RULES = pd.DataFrame([
    {"termo":"petz","categoria":"Pets","subcategoria":"Petshop"},
    {"termo":"petes","categoria":"Pets","subcategoria":"Petshop"},
    {"termo":"farmacia","categoria":"Saúde","subcategoria":"Farmácia"},
    {"termo":"nutag","categoria":"Transporte","subcategoria":"Pedágio"},
    {"termo":"posto","categoria":"Transporte","subcategoria":"Combustível"},
    {"termo":"sim ","categoria":"Transporte","subcategoria":"Combustível"},
    {"termo":"ipiranga","categoria":"Transporte","subcategoria":"Combustível"},
    {"termo":"airbnb","categoria":"Lazer","subcategoria":"Hospedagem"},
    {"termo":"renner","categoria":"Compras Pessoais","subcategoria":"Vestuário"},
    {"termo":"shopping","categoria":"Compras Pessoais","subcategoria":"Shopping"},
    {"termo":"house parts","categoria":"Transporte","subcategoria":"Manutenção Veículo"},
    {"termo":"seg","categoria":"Seguros","subcategoria":"Seguro"},
])

def normalize(text):
    if pd.isna(text): return ""
    text = str(text).upper()
    text = re.sub(r"\s+"," ",text)
    return text.strip()

def read_file(file):
    if file.name.endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)

def detect(df):
    cols = {c.lower():c for c in df.columns}
    return cols.get("date") or cols.get("data"), cols.get("title") or cols.get("descricao"), cols.get("amount") or cols.get("valor")

def prepare(df):
    dcol, tcol, vcol = detect(df)
    df = df[[dcol,tcol,vcol]]
    df.columns = ["data","descricao_original","valor"]
    df["descricao_padronizada"] = df["descricao_original"].apply(normalize)
    df["tipo"] = "Despesa"
    df["categoria"] = ""
    df["subcategoria"] = ""
    df["status"] = "Pendente"
    return df

def apply_rules(df):
    for i,row in df.iterrows():
        desc = row["descricao_padronizada"].lower()
        for _,r in DEFAULT_RULES.iterrows():
            if r["termo"] in desc:
                df.at[i,"categoria"] = r["categoria"]
                df.at[i,"subcategoria"] = r["subcategoria"]
                df.at[i,"status"] = "Automática"
                break
    return df

st.title("💸 Vida OS Financeiro MVP v3")

file = st.file_uploader("Upload extrato")

if file:
    df = prepare(read_file(file))
    df = apply_rules(df)

    # remove pagamentos (valores negativos grandes)
    df_clean = df[df["valor"] > 0]

    st.metric("Total despesas", f"R$ {df_clean['valor'].sum():,.2f}")

    st.write("Transações")
    st.dataframe(df)

    st.write("Resumo (sem pagamento de fatura)")
    resumo = df_clean.groupby("categoria")["valor"].sum().sort_values(ascending=False)
    st.bar_chart(resumo)

