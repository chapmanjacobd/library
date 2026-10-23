from types import SimpleNamespace

from library.shrink import process_table


def test_process_table_output_path_for_named_table():
    args = SimpleNamespace(output_path=None)

    assert process_table._output_path(args, "input.xlsx", "Sales/Q4", 2).name == "input.Sales_Q4.parquet"  # noqa: SLF001
