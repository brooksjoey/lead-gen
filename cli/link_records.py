import os
import sys
from dotenv import load_dotenv
from pyairtable import Api
from pyairtable.formulas import match


def getenv_required(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def single_by_key(table, key_field: str, key_value: str):
    records = table.all(formula=match({key_field: key_value}), fields=[key_field])
    if len(records) == 0:
        return None
    if len(records) > 1:
        ids = [r["id"] for r in records]
        raise SystemExit(f"Ambiguous: multiple records where {key_field}='{key_value}': {ids}")
    return records[0]


def main() -> int:
    load_dotenv()

    token = getenv_required("AIRTABLE_TOKEN")
    base_id = getenv_required("AIRTABLE_BASE_ID")

    t_commands = getenv_required("TABLE_COMMANDS")
    t_specs = getenv_required("TABLE_SPECS")

    field_key = getenv_required("FIELD_COMMAND_KEY")
    field_link = getenv_required("FIELD_LINK_TO_SPEC")

    if len(sys.argv) != 2:
        raise SystemExit("Usage: python link_records.py <CommandKey>")

    command_key = sys.argv[1].strip()
    if not command_key:
        raise SystemExit("CommandKey cannot be empty")

    api = Api(token)
    base = api.base(base_id)

    table_commands = base.table(t_commands)
    table_specs = base.table(t_specs)

    spec = single_by_key(table_specs, field_key, command_key)
    if spec is None:
        raise SystemExit(f"No spec record found in '{t_specs}' where {field_key}='{command_key}'")

    cmd = single_by_key(table_commands, field_key, command_key)
    if cmd is None:
        raise SystemExit(f"No command record found in '{t_commands}' where {field_key}='{command_key}'")

    table_commands.update(cmd["id"], {field_link: [spec["id"]]})

    print(f"OK: linked {t_commands}.{command_key} -> {t_specs}.{spec['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
