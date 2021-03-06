from typing import Optional, Set
import uuid

from snuba import environment
from snuba.query.conditions import (
    binary_condition,
    ConditionFunctions,
    FUNCTION_TO_OPERATOR,
)
from snuba.query.expressions import Column, Expression, FunctionCall, Literal
from snuba.clickhouse.query import Query
from snuba.query.matchers import (
    AnyOptionalString,
    Or,
    Param,
    String,
)
from snuba.query.matchers import Column as ColumnMatch
from snuba.query.matchers import FunctionCall as FunctionCallMatch
from snuba.query.matchers import Literal as LiteralMatch
from snuba.clickhouse.processors import QueryProcessor
from snuba.request.request_settings import RequestSettings
from snuba.utils.metrics.wrapper import MetricsWrapper


metrics = MetricsWrapper(environment.metrics, "api.query.uuid_processor")


class UUIDColumnProcessor(QueryProcessor):
    """
    If a condition is being performed on a column that stores UUIDs (as defined in the constructor)
    then change the condition to use a proper UUID instead of a string.
    """

    def formatted_uuid_pattern(self, suffix: str = "") -> FunctionCallMatch:
        return FunctionCallMatch(
            String("replaceAll"),
            (
                FunctionCallMatch(
                    String("toString"),
                    (
                        Param(
                            "formatted_uuid_column" + suffix,
                            ColumnMatch(None, self.__uuid_column_match),
                        ),
                    ),
                ),
            ),
            with_optionals=True,
        )

    def __init__(self, uuid_columns: Set[str]) -> None:
        self.__unique_uuid_columns = uuid_columns
        self.__uuid_column_match = Or([String(u_col) for u_col in uuid_columns])
        self.uuid_in_condition = FunctionCallMatch(
            Or((String(ConditionFunctions.IN), String(ConditionFunctions.NOT_IN))),
            (
                self.formatted_uuid_pattern(),
                Param("params", FunctionCallMatch(String("tuple"), None)),
            ),
        )
        self.uuid_condition = FunctionCallMatch(
            Or(
                [
                    String(op)
                    for op in FUNCTION_TO_OPERATOR
                    if op not in (ConditionFunctions.IN, ConditionFunctions.NOT_IN)
                ]
            ),
            (
                Or(
                    (
                        Param("literal_0", LiteralMatch(AnyOptionalString())),
                        self.formatted_uuid_pattern("_0"),
                    )
                ),
                Or(
                    (
                        Param("literal_1", LiteralMatch(AnyOptionalString())),
                        self.formatted_uuid_pattern("_1"),
                    )
                ),
            ),
        )
        self.formatted: Optional[str] = None

    def parse_uuid(self, lit: Expression) -> Optional[Expression]:
        if not isinstance(lit, Literal):
            return None

        try:
            parsed = uuid.UUID(str(lit.value))
            return Literal(lit.alias, str(parsed))
        except Exception:
            return None

    def process_condition(self, exp: Expression) -> Expression:
        if not isinstance(exp, FunctionCall):
            return exp

        result = self.uuid_in_condition.match(exp)
        if result is not None:
            column = result.expression("formatted_uuid_column")
            assert isinstance(column, Column)
            new_column = Column(None, column.table_name, column.column_name)

            params_fn = result.expression("params")
            assert isinstance(params_fn, FunctionCall)
            new_fn_params = []
            for param in params_fn.parameters:
                if not isinstance(param, Literal):
                    # Don't convert if any of the parameters are not literals, to avoid
                    # making an invalid query if the UUID literal is buried in some function
                    # e.g. event_id IN tuple(toLower(...), toUpper(...))
                    return exp

                new_lit = self.parse_uuid(param)
                if new_lit is None:
                    # There was a parsing error. Return the expression unchanged.
                    return exp

                new_fn_params.append(new_lit)

            new_function = FunctionCall(
                params_fn.alias, params_fn.function_name, tuple(new_fn_params)
            )
            self.formatted = "function_wrapped"
            return binary_condition(exp.function_name, new_column, new_function)

        result = self.uuid_condition.match(exp)
        if result is not None:
            new_params = []
            for suffix in ["_0", "_1"]:
                if result.contains("literal" + suffix):
                    new_lit = self.parse_uuid(result.expression("literal" + suffix))
                    if new_lit is None:
                        # There was a parsing error. Return the expression unchanged.
                        return exp

                    new_params.append(new_lit)
                elif result.contains("formatted_uuid_column" + suffix):
                    column = result.expression("formatted_uuid_column" + suffix)
                    assert isinstance(column, Column)
                    new_params.append(column)

            left_exp, right_exp = new_params
            self.formatted = "bare_column"
            return binary_condition(exp.function_name, left_exp, right_exp)

        return exp

    def process_query(self, query: Query, request_settings: RequestSettings) -> None:
        condition = query.get_condition_from_ast()
        if condition:
            query.set_ast_condition(condition.transform(self.process_condition))

        prewhere = query.get_prewhere_ast()
        if prewhere:
            query.set_prewhere_ast_condition(prewhere.transform(self.process_condition))

        if self.formatted:
            metrics.increment("query_processed", tags={"type": self.formatted})
