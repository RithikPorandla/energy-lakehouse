"""Database connection utilities."""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()


def get_engine():
    """Create SQLAlchemy engine from environment variables."""
    url = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )
    return create_engine(url)


def load_to_raw(df, table_name):
    """
    Load a DataFrame into the raw schema, replacing existing data.

    Truncates in place (rather than pandas' default drop-and-recreate) so
    downstream dbt staging views — which depend on these tables — survive
    a re-ingestion run instead of erroring with DependentObjectsStillExist.
    """
    engine = get_engine()
    with engine.begin() as conn:
        exists = conn.execute(
            text("select to_regclass(:t)"), {"t": f"raw.{table_name}"}
        ).scalar()
        if exists:
            conn.execute(text(f'truncate table raw."{table_name}"'))

    df.to_sql(
        name=table_name,
        con=engine,
        schema="raw",
        if_exists="append",
        index=False,
    )
    print(f"✓ Loaded {len(df)} rows into raw.{table_name}")
