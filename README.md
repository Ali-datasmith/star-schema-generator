# star-schema-generator

> Automated Data Warehouse Star-Schema Generator powered by DuckDB, Streamlit, and Google Gen AI.

## Architecture & Features
- **Pydantic v2 Contracts**: Enforces strict LLM JSON validation for Star-Schema modeling.
- **DuckDB Sandbox**: In-memory verification of sequence generation and physical schema DDLs.
- **dbt Code Generation**: Automatic generation of `staging` and `marts` models.
- **Streamlit UI**: Custom Glassmorphism interface with execution guard pipelines.

## Project Structure
```text
app/
├── main.py
├── schemas.py
├── services/
├── telemetry/
├── ui/
└── data/samples/
```