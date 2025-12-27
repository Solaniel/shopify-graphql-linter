"""Analyzer core - validates queries and detects deprecations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from graphql import (
    DocumentNode,
    FieldNode,
    GraphQLEnumType,
    GraphQLField,
    GraphQLInputObjectType,
    GraphQLObjectType,
    GraphQLSchema,
    TypeInfo,
    TypeInfoVisitor,
    Visitor,
    parse,
    validate,
    visit,
)
from graphql.error import GraphQLError, GraphQLSyntaxError
from graphql.language.ast import ArgumentNode, EnumValueNode

from .extractors import ExtractedQuery


class IssueSeverity(str, Enum):
    """Severity level for issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueType(str, Enum):
    """Type of issue detected."""

    SYNTAX_ERROR = "syntax_error"
    VALIDATION_ERROR = "validation_error"
    DEPRECATED_FIELD = "deprecated_field"
    DEPRECATED_ARGUMENT = "deprecated_argument"
    DEPRECATED_ENUM_VALUE = "deprecated_enum_value"


@dataclass
class Issue:
    """Represents an issue found during analysis."""

    type: IssueType
    severity: IssueSeverity
    message: str
    source_file: Path
    line: int
    column: int
    field_path: str = ""
    deprecation_reason: Optional[str] = None
    schema_version: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "message": self.message,
            "file": str(self.source_file),
            "line": self.line,
            "column": self.column,
            "field_path": self.field_path,
            "deprecation_reason": self.deprecation_reason,
            "schema_version": self.schema_version,
        }


@dataclass
class QueryAnalysisResult:
    """Result of analyzing a single query."""

    query: ExtractedQuery
    issues: list[Issue] = field(default_factory=list)
    ast: Optional[DocumentNode] = None
    is_valid: bool = True

    @property
    def has_errors(self) -> bool:
        """Check if there are any error-level issues."""
        return any(issue.severity == IssueSeverity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warning-level issues."""
        return any(issue.severity == IssueSeverity.WARNING for issue in self.issues)

    @property
    def error_count(self) -> int:
        """Count error-level issues."""
        return sum(1 for issue in self.issues if issue.severity == IssueSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count warning-level issues."""
        return sum(1 for issue in self.issues if issue.severity == IssueSeverity.WARNING)


class DeprecationVisitor(Visitor):
    """
    AST visitor that detects usage of deprecated fields, arguments, and enum values.
    """

    def __init__(
        self,
        schema: GraphQLSchema,
        type_info: TypeInfo,
        query: ExtractedQuery,
        schema_version: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.schema = schema
        self.type_info = type_info
        self.query = query
        self.schema_version = schema_version
        self.issues: list[Issue] = []
        self._field_path: list[str] = []

    def enter_field(self, node: FieldNode, *args) -> None:
        """Check if field is deprecated."""
        field_def = self.type_info.get_field_def()
        parent_type = self.type_info.get_parent_type()

        if field_def and parent_type:
            self._field_path.append(node.name.value)

            if field_def.deprecation_reason is not None:
                self._add_deprecation_issue(
                    node=node,
                    issue_type=IssueType.DEPRECATED_FIELD,
                    name=f"{parent_type.name}.{node.name.value}",
                    reason=field_def.deprecation_reason,
                )

            # Check arguments
            if node.arguments:
                for arg_node in node.arguments:
                    self._check_argument(arg_node, field_def)

    def leave_field(self, node: FieldNode, *args) -> None:
        """Pop field from path."""
        if self._field_path:
            self._field_path.pop()

    def enter_enum_value(self, node: EnumValueNode, *args) -> None:
        """Check if enum value is deprecated."""
        input_type = self.type_info.get_input_type()
        if input_type:
            # Unwrap non-null and list types
            named_type = input_type
            while hasattr(named_type, "of_type"):
                named_type = named_type.of_type

            if isinstance(named_type, GraphQLEnumType):
                enum_value = named_type.values.get(node.value)
                if enum_value and enum_value.deprecation_reason is not None:
                    self._add_deprecation_issue(
                        node=node,
                        issue_type=IssueType.DEPRECATED_ENUM_VALUE,
                        name=f"{named_type.name}.{node.value}",
                        reason=enum_value.deprecation_reason,
                    )

    def _check_argument(self, arg_node: ArgumentNode, field_def: GraphQLField) -> None:
        """Check if an argument is deprecated."""
        arg_name = arg_node.name.value
        arg_def = field_def.args.get(arg_name)

        if arg_def and arg_def.deprecation_reason is not None:
            self._add_deprecation_issue(
                node=arg_node,
                issue_type=IssueType.DEPRECATED_ARGUMENT,
                name=f"{'.'.join(self._field_path)}(${arg_name})",
                reason=arg_def.deprecation_reason,
            )

    def _add_deprecation_issue(
        self,
        node,
        issue_type: IssueType,
        name: str,
        reason: str,
    ) -> None:
        """Add a deprecation issue."""
        loc = node.loc
        if loc:
            # Convert to 1-based line/column within the query
            rel_line = loc.start_token.line
            rel_col = loc.start_token.column

            # Convert to absolute position in source file
            abs_line = self.query.get_absolute_line(rel_line)
            abs_col = rel_col if rel_line > 1 else self.query.start_col + rel_col - 1
        else:
            abs_line = self.query.start_line
            abs_col = self.query.start_col

        self.issues.append(
            Issue(
                type=issue_type,
                severity=IssueSeverity.WARNING,
                message=f"{name} is deprecated",
                source_file=self.query.source_file,
                line=abs_line,
                column=abs_col,
                field_path=name,
                deprecation_reason=reason,
                schema_version=self.schema_version,
            )
        )


class QueryAnalyzer:
    """
    Analyzes GraphQL queries against a schema.

    Performs:
    1. Syntax parsing
    2. Schema validation
    3. Deprecation detection
    """

    def __init__(self, schema: GraphQLSchema, schema_version: Optional[str] = None) -> None:
        """
        Initialize the analyzer.

        Args:
            schema: GraphQL schema to validate against
            schema_version: Version string for reporting
        """
        self.schema = schema
        self.schema_version = schema_version

    def analyze(self, query: ExtractedQuery) -> QueryAnalysisResult:
        """
        Analyze a single query.

        Args:
            query: Extracted query to analyze

        Returns:
            Analysis result with issues
        """
        result = QueryAnalysisResult(query=query)

        # Phase 1: Parse
        try:
            ast = parse(query.content)
            result.ast = ast
        except GraphQLSyntaxError as e:
            result.is_valid = False
            result.issues.append(
                self._create_syntax_error_issue(query, e)
            )
            return result

        # Phase 2: Validate
        validation_errors = validate(self.schema, ast)
        for error in validation_errors:
            result.is_valid = False
            result.issues.append(
                self._create_validation_error_issue(query, error)
            )

        # Phase 3: Deprecation scan (even if validation failed, to catch as much as possible)
        if ast:
            deprecation_issues = self._scan_deprecations(query, ast)
            result.issues.extend(deprecation_issues)

        return result

    def analyze_many(self, queries: list[ExtractedQuery]) -> list[QueryAnalysisResult]:
        """
        Analyze multiple queries.

        Args:
            queries: List of queries to analyze

        Returns:
            List of analysis results
        """
        return [self.analyze(query) for query in queries]

    def _create_syntax_error_issue(
        self, query: ExtractedQuery, error: GraphQLSyntaxError
    ) -> Issue:
        """Create an issue from a syntax error."""
        # Extract location from error
        locations = error.locations
        if locations:
            loc = locations[0]
            abs_line = query.get_absolute_line(loc.line)
            abs_col = loc.column if loc.line > 1 else query.start_col + loc.column - 1
        else:
            abs_line = query.start_line
            abs_col = query.start_col

        return Issue(
            type=IssueType.SYNTAX_ERROR,
            severity=IssueSeverity.ERROR,
            message=str(error.message),
            source_file=query.source_file,
            line=abs_line,
            column=abs_col,
            schema_version=self.schema_version,
        )

    def _create_validation_error_issue(
        self, query: ExtractedQuery, error: GraphQLError
    ) -> Issue:
        """Create an issue from a validation error."""
        locations = error.locations
        if locations:
            loc = locations[0]
            abs_line = query.get_absolute_line(loc.line)
            abs_col = loc.column if loc.line > 1 else query.start_col + loc.column - 1
        else:
            abs_line = query.start_line
            abs_col = query.start_col

        return Issue(
            type=IssueType.VALIDATION_ERROR,
            severity=IssueSeverity.ERROR,
            message=error.message,
            source_file=query.source_file,
            line=abs_line,
            column=abs_col,
            schema_version=self.schema_version,
        )

    def _scan_deprecations(
        self, query: ExtractedQuery, ast: DocumentNode
    ) -> list[Issue]:
        """Scan AST for deprecated field/argument/enum usage."""
        type_info = TypeInfo(self.schema)
        visitor = DeprecationVisitor(
            schema=self.schema,
            type_info=type_info,
            query=query,
            schema_version=self.schema_version,
        )

        visit(ast, TypeInfoVisitor(type_info, visitor))

        return visitor.issues

