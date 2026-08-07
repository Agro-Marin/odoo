import ast
import tokenize
from tokenize import COMMENT, NAME, OP, STRING, generate_tokens
from typing import IO, TYPE_CHECKING

from babel.util import parse_encoding, parse_future_flags

type _SimpleKeyword = tuple[int | tuple[int, int] | tuple[int, str], ...] | None
type _Keyword = dict[int | None, _SimpleKeyword] | _SimpleKeyword
type _ExtractionResult = tuple[int, str, str | tuple[str, ...], list[str]]

if TYPE_CHECKING:
    from collections.abc import Collection, Generator, Mapping
    from typing import TypedDict

    class _PyOptions(TypedDict, total=False):
        encoding: str


FSTRING_START = tokenize.FSTRING_START if hasattr(tokenize, "FSTRING_START") else None
FSTRING_MIDDLE = (
    tokenize.FSTRING_MIDDLE if hasattr(tokenize, "FSTRING_MIDDLE") else None
)
FSTRING_END = tokenize.FSTRING_END if hasattr(tokenize, "FSTRING_END") else None


def _parse_python_string(value: str, encoding: str, future_flags: int) -> str | None:
    code = compile(
        f"# coding={encoding!s}\n{value}",
        "<string>",
        "eval",
        ast.PyCF_ONLY_AST | future_flags,
    )
    if isinstance(code, ast.Expression):
        body = code.body
        if isinstance(body, ast.Constant):
            return body.value
        if isinstance(body, ast.JoinedStr):
            if all(isinstance(node, ast.Constant) for node in body.values):
                return "".join(node.value for node in body.values)
    return None


def extract_python(
    fileobj: IO[bytes],
    keywords: Mapping[str, _Keyword],
    comment_tags: Collection[str],
    options: _PyOptions,
) -> Generator[_ExtractionResult]:
    encoding = parse_encoding(fileobj) or options.get("encoding", "utf-8")
    future_flags = parse_future_flags(fileobj, encoding)

    def next_line():
        return fileobj.readline().decode(encoding)

    tokens = generate_tokens(next_line)

    function_stack = []
    last_name = None
    in_def = False
    in_translator_comments = False
    translator_comments = []
    message_buffer = []
    current_fstring_start = None

    for token, value, (lineno, _), _, _ in tokens:
        if token == NAME and value in ("def", "class"):
            in_def = True
            continue

        if in_def and token == OP and value in ("(", ":"):
            in_def = False
            continue

        if token == OP and value == "(" and last_name:
            cur_translator_comments = translator_comments
            if function_stack and function_stack[-1]["function_lineno"] == lineno:
                cur_translator_comments = function_stack[-1]["translator_comments"]

            function_stack.append(
                {
                    "function_lineno": lineno,
                    "function_name": last_name,
                    "message_lineno": None,
                    "messages": [],
                    "translator_comments": cur_translator_comments,
                }
            )
            last_name = None
            translator_comments = []
            message_buffer.clear()

        elif token == COMMENT:
            value = value[1:].strip()
            if in_translator_comments and translator_comments[-1][0] == lineno - 1:
                translator_comments.append((lineno, value))
                continue

            for comment_tag in comment_tags:
                if value.startswith(comment_tag):
                    in_translator_comments = True
                    translator_comments.append((lineno, value))
                    break

        elif function_stack and function_stack[-1]["function_name"] in keywords:
            if token == OP and value == ")":
                messages = function_stack[-1]["messages"]
                lineno = (
                    function_stack[-1]["message_lineno"]
                    or function_stack[-1]["function_lineno"]
                )
                cur_translator_comments = function_stack[-1]["translator_comments"]

                if message_buffer:
                    messages.append("".join(message_buffer))
                    message_buffer.clear()
                else:
                    messages.append(None)

                messages = tuple(messages) if len(messages) > 1 else messages[0]
                if (
                    cur_translator_comments
                    and cur_translator_comments[-1][0] < lineno - 1
                ):
                    cur_translator_comments = []

                yield (
                    lineno,
                    function_stack[-1]["function_name"],
                    messages,
                    [comment[1] for comment in cur_translator_comments],
                )

                function_stack.pop()

            elif token == STRING:
                string_value = _parse_python_string(value, encoding, future_flags)
                if not function_stack[-1]["message_lineno"]:
                    function_stack[-1]["message_lineno"] = lineno
                if string_value is not None:
                    message_buffer.append(string_value)

            elif token == FSTRING_START:
                current_fstring_start = value
            elif token == FSTRING_MIDDLE:
                if current_fstring_start is not None:
                    current_fstring_start += value
            elif token == FSTRING_END:
                if current_fstring_start is not None:
                    fstring = current_fstring_start + value
                    string_value = _parse_python_string(fstring, encoding, future_flags)
                    if string_value is not None:
                        message_buffer.append(string_value)

            elif token == OP and value == ",":
                if message_buffer:
                    function_stack[-1]["messages"].append("".join(message_buffer))
                    message_buffer.clear()
                else:
                    function_stack[-1]["messages"].append(None)

        elif function_stack and token == OP and value == ")":
            function_stack.pop()

        if in_translator_comments and translator_comments[-1][0] < lineno:
            in_translator_comments = False

        if token == NAME:
            last_name = value
            if function_stack and not function_stack[-1]["message_lineno"]:
                function_stack[-1]["message_lineno"] = lineno

        if current_fstring_start is not None and token not in {
            FSTRING_START,
            FSTRING_MIDDLE,
        }:
            current_fstring_start = None
