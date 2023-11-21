from xklb.site_extract import nosql_to_sql


def test_tables():
    output = nosql_to_sql({"people": [{"name": "John", "age": 30}, {"name": "Jane", "age": 25}]})
    assert output == [{"table_name": "people", "data": [{"name": "John", "age": 30}, {"name": "Jane", "age": 25}]}]


def test_simple_dict():
    assert nosql_to_sql({"name": "John", "age": 30}) == [{"table_name": None, "data": [{"name": "John", "age": 30}]}]
    assert nosql_to_sql({"1": 1, "2": "ba", "3": False, "4": 1.2}) == [
        {"table_name": None, "data": [{"1": 1, "2": "ba", "3": False, "4": 1.2}]}
    ]


def test_nested_dict():
    output = nosql_to_sql({"name": "John", "address": {"street": "123 Main St", "city": "Anytown"}})
    assert output == [
        {"table_name": None, "data": [{"name": "John", "address_street": "123 Main St", "address_city": "Anytown"}]}
    ]


def test_nested_dict2():
    assert nosql_to_sql({"1": {"2": 1, "3": "ba"}}) == [{"table_name": None, "data": [{"1_2": 1, "1_3": "ba"}]}]


def test_nested_dict_with_lists():
    output = nosql_to_sql({"data1": [{"a": 1}, {"c": 2}], "data2": [{"g": 10}, {"h": 1}]})
    assert output == [
        {"table_name": "data1", "data": [{"a": 1}, {"c": 2}]},
        {"table_name": "data2", "data": [{"g": 10}, {"h": 1}]},
    ]


def test_nested_dict_with_lists2():
    output = nosql_to_sql(
        {
            "data1": [{"a": 1, "b": [2, 3, 4]}, {"c": {"d": [5, 6, 7]}}],
            "data2": {"e": [8, 9], "f": [{"g": 10}, {"h": [11, 12]}]},
        }
    )
    assert output == [
        {"table_name": "data1_b", "data": [{"v": 2}, {"v": 3}, {"v": 4}]},
        {"table_name": "data1", "data": [{"a": 1}]},
        {"table_name": "data1_d", "data": [{"v": 5}, {"v": 6}, {"v": 7}]},
        {"table_name": "data2_e", "data": [{"v": 8}, {"v": 9}]},
        {"table_name": "data2_f", "data": [{"g": 10}]},
        {"table_name": "data2_f_h", "data": [{"v": 11}, {"v": 12}]},
    ]


def test_dict_with_list():
    assert nosql_to_sql({"1": [1, 2], "2": "ba"}) == [
        {"table_name": "1", "data": [{"v": 1}, {"v": 2}]},
        {"table_name": "1_root", "data": [{"2": "ba"}]},
    ]


def test_dict_with_list_of_dicts():
    assert nosql_to_sql({"1": [{"2": "ba", "3": 1}, {"2": "barfoo", "3": 3}], "2": "ba"}) == [
        {"table_name": "1", "data": [{"2": "ba", "3": 1}, {"2": "barfoo", "3": 3}]},
        {"table_name": "1_root", "data": [{"2": "ba"}]},
    ]


def test_dict_with_nested_list():
    assert nosql_to_sql({"1": [[1], [2, 3]]}) == [{"table_name": "1", "data": [{"v": [1]}, {"v": [2, 3]}]}]


def test_dict_with_nested_list_of_dicts():
    assert nosql_to_sql({"1": [[{"2": 3}, {"2": 4}], [{"2": 5}, {"2": 6}]]}) == [
        {"table_name": "1", "data": [{"v": [{"2": 3}, {"2": 4}]}, {"v": [{"2": 5}, {"2": 6}]}]}
        # {'table_name': '1', 'data': [{"2": 3}, {"2": 4}, {"2": 5}, {"2": 6}]}
    ]


def test_dict_with_list_of_dicts_with_list():
    assert nosql_to_sql({"1": [{"2": "ba", "3": [1, 2]}, {"2": "barfoo", "3": [3, 4]}], "5": "bc"}) == [
        {"table_name": "1_3", "data": [{"v": 1}, {"v": 2}, {"v": 3}, {"v": 4}]},
        {"table_name": "1", "data": [{"2": "ba"}, {"2": "barfoo"}]},
        {"table_name": "1_root", "data": [{"5": "bc"}]},
    ]


def test_simple_list():
    assert nosql_to_sql(["1", "2", "ba"]) == [{"table_name": None, "data": [{"v": "1"}, {"v": "2"}, {"v": "ba"}]}]


def test_nested_list():
    assert nosql_to_sql([[3, 1, 1, "da"], [2, 1, 3, "ba"]]) == [
        {"table_name": None, "data": [{"v": [3, 1, 1, "da"]}, {"v": [2, 1, 3, "ba"]}]}
    ]


def test_nested_list_weird():
    assert nosql_to_sql(["1", [2, 1, 3, "ba"]]) == [{"table_name": None, "data": [{"v": "1"}, {"v": [2, 1, 3, "ba"]}]}]


def test_list_with_dict():
    assert nosql_to_sql([{"1": "boo", "2": "ba"}]) == [{"table_name": None, "data": [{"1": "boo", "2": "ba"}]}]


def test_list_with_dict_of_str_lists():
    assert nosql_to_sql([{"1": ["2", "ba", "3"]}, {"2": ["barfoo", "3"]}]) == [
        {"table_name": None, "data": [{"1": "2, ba, 3"}, {"2": "barfoo, 3"}]}
    ]


def test_list_with_nested_dict():
    assert nosql_to_sql([{"1": {"1": {"2": "win"}}}]) == [{"table_name": None, "data": [{"2": "win"}]}]


def test_list_with_nested_dict_of_lists():
    assert nosql_to_sql([{"1": {"1": {"2": [2, 3]}}}]) == [{"table_name": "2", "data": [{"v": 2}, {"v": 3}]}]
