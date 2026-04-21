# Vida OS Financeiro MVP

MVP em Streamlit para:
- receber upload de extrato CSV/XLSX
- categorizar automaticamente por regras
- permitir ajuste manual do que ficar pendente
- baixar transações e regras atualizadas

## Rodar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Estrutura esperada do arquivo
O app tenta detectar colunas equivalentes a:
- `date` ou `data`
- `title` ou `descricao`
- `amount` ou `valor`

## Deploy no Streamlit Community Cloud
1. Crie um repositório no GitHub.
2. Envie `app.py` e `requirements.txt`.
3. Entre em `share.streamlit.io`.
4. Clique em **Create app**.
5. Escolha seu repositório, branch e o arquivo `app.py`.
6. Publique.

## Limitação atual
As regras ficam na sessão do usuário. Para preservar seu aprendizado entre usos, baixe o arquivo de regras atualizado e suba novamente na próxima sessão.

## Próxima evolução recomendada
- autenticação
- banco PostgreSQL/Supabase
- histórico por usuário
- orçamento por categoria
- alertas e insights
