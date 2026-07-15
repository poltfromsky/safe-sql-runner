import os
import re
import sys

from dotenv import load_dotenv

try:
    import psycopg2
    import psycopg2.errors
except ImportError:
    print(
        "Ошибка: не установлен пакет psycopg2-binary. "
        "Выполните: pip install -r requirements.txt"
    )
    sys.exit(1)

try:
    from tabulate import tabulate
except ImportError:
    tabulate = None


FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REPLACE", "EXECUTE", "LOCK", "COPY",
    "MERGE", "REVOKE", "VACUUM", "COMMENT", "CALL",
)

SELECT_PATTERN = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
LIMIT_PATTERN = re.compile(r"\bLIMIT\b", re.IGNORECASE)
DEFAULT_LIMIT = 5 #лимит по умолчанию

BLOCKED_MESSAGE = "Ошибка: разрешены только SELECT-запросы"


def strip_query(raw_query): #очищает запрос от пробелов и точки с запятой в конце
    query = raw_query.strip()
    query = query.rstrip(";").strip()
    return query


def validate_select_only(query): #проверяет, что запрос является безопасным SELECT-запросом
    if not query:
        raise ValueError("Ошибка: пустой запрос")
    if ";" in query:
        raise ValueError("Ошибка: разрешён только один запрос за раз")

    if not SELECT_PATTERN.match(query):
        raise ValueError(BLOCKED_MESSAGE)

    upper_query = query.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper_query):
            raise ValueError(BLOCKED_MESSAGE)


def ensure_limit(query: str, default_limit: int = DEFAULT_LIMIT) -> str: #добавляет LIMIT в запрос, если его там нет
    if LIMIT_PATTERN.search(query):
        return query #LIMIT уже есть, ничего не меняется
    return f"{query} LIMIT {default_limit}"


def get_connection_params(): #загружает параметры подключения к PostgreSQL из .env файла
    load_dotenv()
    params = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    }
    missing = [key for key in ("dbname", "user") if not params[key]] #проверека на заданность обязатльных параметров
    if missing:
        raise RuntimeError(
            "Ошибка: не заданы обязательные переменные окружения "
            f"({', '.join(missing)}). Скопируйте .env.example в .env "
            "и укажите параметры подключения."
        )
    return params


def run_query(conn, query):  #выполняет SQL-запрос и возвращает результат
    with conn.cursor() as cursor:
        cursor.execute(query)
        if cursor.description is None:
            return [], []  #если нет результата - возвращает пустые списки
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
    return columns, rows


def print_results(columns, rows): #выводит результаты запроса в виде таблицы
    if not columns and not rows:
        print("Запрос выполнен успешно. Строк не найдено.")
        return

    if tabulate is not None:
        print(tabulate(rows, headers=columns, tablefmt="psql"))
    else:
        print(" | ".join(columns))
        print("-" * (len(columns) * 12))
        for row in rows:
            print(" | ".join(str(value) for value in row))

    print(f"\nВсего строк: {len(rows)}")


def read_query(): #чтение SQL-запроса
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:]).strip()
        if query == "": #проверка на пустой запрос
            print("Ошибка: пустой запрос")
            sys.exit(1)
        return query
    return input("Введите SQL-запрос: ")

raw_query = read_query()
query = strip_query(raw_query)

try:
    validate_select_only(query)
except ValueError as exc:
    print(exc)
    sys.exit(1) #выход, чтобы не выполнять опасный запрос
safe_query = ensure_limit(query)
try:
    params = get_connection_params()
except RuntimeError as exc:
    print(exc)
    sys.exit(1)

conn = None


try:
    conn = psycopg2.connect(**params)
except psycopg2.OperationalError as exc:
    print(f"Ошибка подключения к базе данных: {str(exc).strip()}")
    sys.exit(1)
try:
    columns, rows = run_query(conn, safe_query)
    print_results(columns, rows)
except psycopg2.errors.SyntaxError as exc:
    print(f"Ошибка синтаксиса SQL: {str(exc).strip()}")
except psycopg2.Error as exc:
    print(f"Ошибка выполнения запроса: {str(exc).strip()}")
except Exception as exc: #на последнем рубеже скрипт не должен падать
    print(f"Непредвиденная ошибка: {exc}")
finally:
    if conn:
        conn.close()
