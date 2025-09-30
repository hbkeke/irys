import sys
from pathlib import Path

import pandas as pd
from loguru import logger
from sqlalchemy.sql.schema import MetaData

from data.config import FILES_DIR
from utils.db_api.db import DB


def load_all_database_url():
    files_dir = Path(FILES_DIR)
    databases = list(files_dir.glob("*.db"))
    if not databases:
        raise FileNotFoundError("Не найдены базы данных для экспорта, проверьте что база данных инициализирована.")
    return [str(database) for database in databases]


class CSVExporter:
    def __init__(self):
        self.output_dir: Path = Path(FILES_DIR)
        try:
            self._database_urls = load_all_database_url()
        except FileNotFoundError as e:
            logger.error("Ошибка при инициализации экспортера: {0}", e)
            sys.exit(1)

    def __call__(self, *args, **kwargs):
        return self.process_model_to_export()

    def _connect_to_db(self, database_url: str) -> DB | None:
        try:
            return DB(db_url=f"sqlite:///{database_url}")
        except Exception as e:
            logger.error("Не удалось подключиться к БД: {0}", e)
            return None

    def read_model_to_export(self, database_url: str):
        database = self._connect_to_db(database_url)
        if database is None:
            logger.error("Пропускаем БД")
            return False

        metadata = MetaData()
        metadata.reflect(bind=database.engine)
        tables = metadata.tables
        if not tables:
            logger.error("Не найдены таблицы в БД {0}", database_url)
            return False

        return self.export_to_csv(tables, database.engine, database_url)

    def export_to_csv(self, tables: dict, engine, database_url: str):
        logger.debug("Начинаем экспорт в CSV")
        db_name = Path(database_url).stem  # wallets.db → wallets
        db_file = Path(database_url).name  # wallets.db
        csv_path = self.output_dir / f"{db_name}.csv"

        all_data = []
        for table_name in tables.keys():
            df = pd.read_sql_table(table_name, engine)

            df = df.drop(columns=["private_key"], errors="ignore")

            df["source_table"] = table_name
            all_data.append(df)

        if all_data:
            final_df = pd.concat(all_data, ignore_index=True)
            final_df.to_csv(csv_path, index=False)
            logger.debug("CSV экспортирован: {csv_path}", csv_path=csv_path)
            return db_file, str(csv_path)

        return False

    def process_model_to_export(self):
        database_urls = load_all_database_url()
        results = [self.read_model_to_export(db_url) for db_url in database_urls]
        return results, self.output_dir


def export_to_csv():
    exporter = CSVExporter()
    results, _ = exporter()

    success = all(bool(r) for r in results)
    return success, results
