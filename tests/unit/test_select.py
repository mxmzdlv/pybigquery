import datetime
from decimal import Decimal

import pytest
import sqlalchemy

import pybigquery.sqlalchemy_bigquery

from conftest import setup_table, sqlalchemy_1_3_or_higher


def test_labels_not_forced(faux_conn):
    table = setup_table(faux_conn, "t", sqlalchemy.Column("id", sqlalchemy.Integer))
    result = faux_conn.execute(sqlalchemy.select([table.c.id]))
    assert result.keys() == ["id"]  # Look! Just the column name!


def dtrepr(v):
    return f"{v.__class__.__name__.upper()} {repr(str(v))}"


@pytest.mark.parametrize(
    "type_,val,btype,vrep",
    [
        (sqlalchemy.String, "myString", "STRING", repr),
        (sqlalchemy.Text, "myText", "STRING", repr),
        (sqlalchemy.Unicode, "myUnicode", "STRING", repr),
        (sqlalchemy.UnicodeText, "myUnicodeText", "STRING", repr),
        (sqlalchemy.Integer, 424242, "INT64", repr),
        (sqlalchemy.SmallInteger, 42, "INT64", repr),
        (sqlalchemy.BigInteger, 1 << 60, "INT64", repr),
        (sqlalchemy.Numeric, Decimal(42), "NUMERIC", str),
        (sqlalchemy.Float, 4.2, "FLOAT64", repr),
        (
            sqlalchemy.DateTime,
            datetime.datetime(2021, 2, 3, 4, 5, 6, 123456),
            "DATETIME",
            dtrepr,
        ),
        (sqlalchemy.Date, datetime.date(2021, 2, 3), "DATE", dtrepr),
        (sqlalchemy.Time, datetime.time(4, 5, 6, 123456), "TIME", dtrepr),
        (sqlalchemy.Boolean, True, "BOOL", "true"),
        (sqlalchemy.REAL, 1.42, "FLOAT64", repr),
        (sqlalchemy.FLOAT, 0.42, "FLOAT64", repr),
        (sqlalchemy.NUMERIC, Decimal(4.25), "NUMERIC", str),
        (sqlalchemy.NUMERIC(39), Decimal(4.25), "BIGNUMERIC", str),
        (sqlalchemy.NUMERIC(30, 10), Decimal(4.25), "BIGNUMERIC", str),
        (sqlalchemy.NUMERIC(39, 10), Decimal(4.25), "BIGNUMERIC", str),
        (sqlalchemy.DECIMAL, Decimal(0.25), "NUMERIC", str),
        (sqlalchemy.DECIMAL(39), Decimal(4.25), "BIGNUMERIC", str),
        (sqlalchemy.DECIMAL(30, 10), Decimal(4.25), "BIGNUMERIC", str),
        (sqlalchemy.DECIMAL(39, 10), Decimal(4.25), "BIGNUMERIC", str),
        (sqlalchemy.INTEGER, 434343, "INT64", repr),
        (sqlalchemy.INT, 444444, "INT64", repr),
        (sqlalchemy.SMALLINT, 43, "INT64", repr),
        (sqlalchemy.BIGINT, 1 << 61, "INT64", repr),
        (
            sqlalchemy.TIMESTAMP,
            datetime.datetime(2021, 2, 3, 4, 5, 7, 123456),
            "TIMESTAMP",
            lambda v: f"TIMESTAMP {repr(str(v))}",
        ),
        (
            sqlalchemy.DATETIME,
            datetime.datetime(2021, 2, 3, 4, 5, 8, 123456),
            "DATETIME",
            dtrepr,
        ),
        (sqlalchemy.DATE, datetime.date(2021, 2, 4), "DATE", dtrepr),
        (sqlalchemy.TIME, datetime.time(4, 5, 7, 123456), "TIME", dtrepr),
        (sqlalchemy.TIME, datetime.time(4, 5, 7), "TIME", dtrepr),
        (sqlalchemy.TEXT, "myTEXT", "STRING", repr),
        (sqlalchemy.VARCHAR, "myVARCHAR", "STRING", repr),
        (sqlalchemy.NVARCHAR, "myNVARCHAR", "STRING", repr),
        (sqlalchemy.CHAR, "myCHAR", "STRING", repr),
        (sqlalchemy.NCHAR, "myNCHAR", "STRING", repr),
        (sqlalchemy.BINARY, b"myBINARY", "BYTES", repr),
        (sqlalchemy.VARBINARY, b"myVARBINARY", "BYTES", repr),
        (sqlalchemy.BOOLEAN, False, "BOOL", "false"),
        (sqlalchemy.ARRAY(sqlalchemy.Integer), [1, 2, 3], "ARRAY<INT64>", repr),
        (
            sqlalchemy.ARRAY(sqlalchemy.DATETIME),
            [
                datetime.datetime(2021, 2, 3, 4, 5, 6),
                datetime.datetime(2021, 2, 3, 4, 5, 7, 123456),
                datetime.datetime(2021, 2, 3, 4, 5, 8, 123456),
            ],
            "ARRAY<DATETIME>",
            lambda a: "[" + ", ".join(dtrepr(v) for v in a) + "]",
        ),
    ],
)
def test_typed_parameters(faux_conn, type_, val, btype, vrep):
    col_name = "foo"
    table = setup_table(faux_conn, "t", sqlalchemy.Column(col_name, type_))

    assert faux_conn.test_data["execute"].pop()[0].strip() == (
        f"CREATE TABLE `t` (\n" f"\t`{col_name}` {btype}\n" f")"
    )

    faux_conn.execute(table.insert().values(**{col_name: val}))

    if btype.startswith("ARRAY<"):
        btype = btype[6:-1]

    assert faux_conn.test_data["execute"][-1] == (
        f"INSERT INTO `t` (`{col_name}`) VALUES (%({col_name}:{btype})s)",
        {col_name: val},
    )

    faux_conn.execute(
        table.insert()
        .values(**{col_name: sqlalchemy.literal(val, type_)})
        .compile(
            dialect=pybigquery.sqlalchemy_bigquery.BigQueryDialect(),
            compile_kwargs=dict(literal_binds=True),
        )
    )

    if not isinstance(vrep, str):
        vrep = vrep(val)

    assert faux_conn.test_data["execute"][-1] == (
        f"INSERT INTO `t` (`{col_name}`) VALUES ({vrep})", {})

    assert list(map(list, faux_conn.execute(sqlalchemy.select([table])))) == [[val]] * 2
    assert faux_conn.test_data["execute"][-1][0] == 'SELECT `t`.`foo` \nFROM `t`'

    assert list(map(list,
                    faux_conn.execute(
                        sqlalchemy.select([table.c.foo], use_labels=True)))
                ) == [[val]] * 2
    assert faux_conn.test_data["execute"][-1][0] == (
        'SELECT `t`.`foo` AS `t_foo` \nFROM `t`')


def test_select_json(faux_conn, metadata):
    table = sqlalchemy.Table("t", metadata, sqlalchemy.Column("x", sqlalchemy.JSON))

    faux_conn.ex("create table t (x RECORD)")
    faux_conn.ex("""insert into t values ('{"y": 1}')""")

    row = list(faux_conn.execute(sqlalchemy.select([table])))[0]
    # We expect the raw string, because sqlite3, unlike BigQuery
    # doesn't deserialize for us.
    assert row.x == '{"y": 1}'


def test_select_label_starts_w_digit(faux_conn):
    # Make sure label names are legal identifiers
    faux_conn.execute(sqlalchemy.select([sqlalchemy.literal(1).label("2foo")]))
    assert faux_conn.test_data["execute"][-1][0] == 'SELECT %(param_1:INT64)s AS `_2foo`'


def test_force_quote(faux_conn):
    from  sqlalchemy.sql.elements import quoted_name
    table = setup_table(
        faux_conn,
        "t",
        sqlalchemy.Column(quoted_name("foo", True), sqlalchemy.Integer),
        )
    faux_conn.execute(sqlalchemy.select([table]))
    assert faux_conn.test_data["execute"][-1][0] == (
        'SELECT `t`.`foo` \nFROM `t`')


def test_disable_quote(faux_conn):
    from  sqlalchemy.sql.elements import quoted_name
    table = setup_table(
        faux_conn,
        "t",
        sqlalchemy.Column(quoted_name("foo", False), sqlalchemy.Integer),
        )
    faux_conn.execute(sqlalchemy.select([table]))
    assert faux_conn.test_data["execute"][-1][0] == (
        'SELECT `t`.foo \nFROM `t`')


def test_select_in_lit(faux_conn):
    [[isin]] = faux_conn.execute(sqlalchemy.select([sqlalchemy.literal(1).in_([1,2,3])]))
    assert isin
    assert faux_conn.test_data["execute"][-1] == (
        "SELECT %(param_1:INT64)s IN "
        "(%(param_2:INT64)s, %(param_3:INT64)s, %(param_4:INT64)s) AS `anon_1`",
        {'param_1': 1, 'param_2': 1, 'param_3': 2, 'param_4': 3},
        )


def test_select_in_param(faux_conn):
    [[isin]] = faux_conn.execute(sqlalchemy.select([
        sqlalchemy.literal(1).in_(sqlalchemy.bindparam("q", expanding=True))
        ]), dict(q=[1,2,3]))
    assert isin
    assert faux_conn.test_data["execute"][-1] == (
        "SELECT %(param_1:INT64)s IN UNNEST("
        "[ %(q_1:INT64)s, %(q_2:INT64)s, %(q_3:INT64)s ]"
        ") AS `anon_1`",
        {'param_1': 1, 'q_1': 1, 'q_2': 2, 'q_3': 3})


@sqlalchemy_1_3_or_higher
def test_select_in_param_empty(faux_conn):
    [[isin]] = faux_conn.execute(sqlalchemy.select([
        sqlalchemy.literal(1).in_(sqlalchemy.bindparam("q", expanding=True))
        ]), dict(q=[]))
    assert not isin
    assert faux_conn.test_data["execute"][-1] == (
        "SELECT %(param_1:INT64)s IN UNNEST("
        "[  ]"
        ") AS `anon_1`",
        {'param_1': 1})


def test_select_notin_lit(faux_conn):
    [[isnotin]] = faux_conn.execute(sqlalchemy.select([
        sqlalchemy.literal(0).notin_([1, 2,3])
        ]))
    assert isnotin
    assert faux_conn.test_data["execute"][-1] == (
        "SELECT %(param_1:INT64)s NOT IN "
        "(%(param_2:INT64)s, %(param_3:INT64)s, %(param_4:INT64)s) AS `anon_1`",
        {'param_1': 0, 'param_2': 1, 'param_3': 2, 'param_4': 3},
        )


def test_select_notin_param(faux_conn):
    [[isnotin]] = faux_conn.execute(sqlalchemy.select([
        sqlalchemy.literal(1).notin_(sqlalchemy.bindparam("q", expanding=True))
        ]), dict(q=[1,2,3]))
    assert not isnotin
    assert faux_conn.test_data["execute"][-1] == (
        "SELECT %(param_1:INT64)s NOT IN UNNEST("
        "[ %(q_1:INT64)s, %(q_2:INT64)s, %(q_3:INT64)s ]"
        ") AS `anon_1`",
        {'param_1': 1, 'q_1': 1, 'q_2': 2, 'q_3': 3})


@sqlalchemy_1_3_or_higher
def test_select_notin_param_empty(faux_conn):
    [[isnotin]] = faux_conn.execute(sqlalchemy.select([
        sqlalchemy.literal(1).notin_(sqlalchemy.bindparam("q", expanding=True))
        ]), dict(q=[]))
    assert isnotin
    assert faux_conn.test_data["execute"][-1] == (
        "SELECT %(param_1:INT64)s NOT IN UNNEST("
        "[  ]"
        ") AS `anon_1`",
        {'param_1': 1})
