import io
from textwrap import dedent
from typing import TYPE_CHECKING

from babel.messages.jslexer import Token, line_re, tokenize, unquote_string

type _SimpleKeyword = tuple[int | tuple[int, int] | tuple[int, str], ...] | None
type _Keyword = dict[int | None, _SimpleKeyword] | _SimpleKeyword
type _ExtractionResult = tuple[int, str, str | tuple[str, ...], list[str]]

if TYPE_CHECKING:
    from collections.abc import Collection, Generator, Mapping
    from typing import Protocol, TypedDict

    from _typeshed import SupportsRead, SupportsReadline

    class _FileObj(SupportsRead[bytes], SupportsReadline[bytes], Protocol):
        def seek(self, offset: int, whence: int = ..., /) -> int: ...
        def tell(self) -> int: ...

    class _JSOptions(TypedDict, total=False):
        encoding: str
        jsx: bool
        template_string: bool
        parse_template_string: bool


def parse_template_string(
    template_string: str,
    keywords: Mapping[str, _Keyword],
    comment_tags: Collection[str],
    options: _JSOptions,
    lineno: int = 0,
    keyword: str = "",
) -> Generator[_ExtractionResult]:
    prev_character = None
    escaped = False
    level = 0
    #: The quote character that opened the string we are inside, or "" when we
    #: are not inside one. This was `False`/quote-char, so `inside_str ==
    #: character` compared a bool against a str on every non-string character.
    inside_str = ""
    expression_contents = ""
    for character in template_string[1:-1]:
        if not inside_str and character in ('"', "'", "`"):
            inside_str = character
        elif inside_str == character and not escaped:
            inside_str = ""
        if level or keyword:
            expression_contents += character
        if not inside_str:
            if character == "{" and prev_character == "$":
                if keyword:
                    break
                level += 1
            elif level and character == "}":
                level -= 1
                if level == 0 and expression_contents:
                    expression_contents = expression_contents[0:-1]
                    fake_file_obj = io.BytesIO(expression_contents.encode())
                    yield from extract_javascript(
                        fake_file_obj, keywords, comment_tags, options, lineno - 1
                    )
                    lineno += len(line_re.findall(expression_contents))
                    expression_contents = ""
        escaped = character == "\\" and not escaped
        prev_character = character
    if keyword:
        yield (lineno, keyword, expression_contents, [])


def extract_javascript(
    fileobj: _FileObj,
    keywords: Mapping[str, _Keyword],
    comment_tags: Collection[str],
    options: _JSOptions,
    lineno_offset: int = 0,
) -> Generator[_ExtractionResult]:
    encoding = options.get("encoding", "utf-8")
    dotted = any("." in kw for kw in keywords)

    last_token = None
    function_stack = []
    in_def = False
    in_translator_comments = False
    translator_comments = []
    message_buffer = []

    for token in tokenize(
        fileobj.read().decode(encoding),
        jsx=options.get("jsx", True),
        dotted=dotted,
        template_string=options.get("template_string", True),
    ):
        token: Token = Token(token.type, token.value, token.lineno + lineno_offset)
        if token.type == "name" and token.value in ("class", "function"):
            in_def = True
            continue

        elif in_def and token.type == "operator" and token.value in ("(", "{"):
            in_def = False
            continue

        elif (
            last_token and last_token.type == "name" and token.type == "template_string"
        ):
            string_value = unquote_string(token.value)
            cur_translator_comments = translator_comments
            if (
                function_stack
                and function_stack[-1]["function_lineno"] == last_token.lineno
            ):
                cur_translator_comments = function_stack[-1]["translator_comments"]

            function_stack.append(
                {
                    "function_lineno": last_token.lineno,
                    "function_name": last_token.value,
                    "message_lineno": token.lineno,
                    "messages": [string_value],
                    "translator_comments": cur_translator_comments,
                }
            )
            translator_comments = []
            message_buffer.clear()

            last_token = token
            token = Token("operator", ")", token.lineno)

        if (
            options.get("parse_template_string", True)
            and (
                not last_token
                or last_token.type != "name"
                or last_token.value not in keywords
            )
            and token.type == "template_string"
        ):
            keyword = ""
            if function_stack and function_stack[-1]["function_name"] in keywords:
                keyword = function_stack[-1]["function_name"]
            yield from parse_template_string(
                token.value,
                keywords,
                comment_tags,
                options,
                token.lineno,
                keyword,
            )

        elif token.type == "operator" and token.value == "(":
            if last_token and last_token.type == "name":
                cur_translator_comments = translator_comments
                if (
                    function_stack
                    and function_stack[-1]["function_lineno"] == last_token.lineno
                ):
                    cur_translator_comments = function_stack[-1]["translator_comments"]

                function_stack.append(
                    {
                        "function_lineno": token.lineno,
                        "function_name": last_token.value,
                        "message_lineno": None,
                        "messages": [],
                        "translator_comments": cur_translator_comments,
                    }
                )
                translator_comments = []
                message_buffer.clear()

        elif token.type == "linecomment":
            value = token.value[2:].strip()
            if (
                in_translator_comments
                and translator_comments[-1][0] == token.lineno - 1
            ):
                translator_comments.append((token.lineno, value))
                continue

            for comment_tag in comment_tags:
                if value.startswith(comment_tag):
                    in_translator_comments = True
                    translator_comments.append((token.lineno, value))
                    break

        elif token.type == "multilinecomment":
            translator_comments = []
            value = token.value[2:-2].strip()
            for comment_tag in comment_tags:
                if value.startswith(comment_tag):
                    lines = value.splitlines()
                    if lines:
                        lines[0] = lines[0].strip()
                        lines[1:] = dedent("\n".join(lines[1:])).splitlines()
                        for offset, line in enumerate(lines):
                            translator_comments.append((token.lineno + offset, line))
                    break

        elif function_stack and function_stack[-1]["function_name"] in keywords:
            if token.type == "operator" and token.value == ")":
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

            elif token.type in ("string", "template_string"):
                if last_token.type == "name":
                    message_buffer.clear()
                else:
                    string_value = unquote_string(token.value)
                    if not function_stack[-1]["message_lineno"]:
                        function_stack[-1]["message_lineno"] = token.lineno
                    if string_value is not None:
                        message_buffer.append(string_value)

            elif token.type == "operator" and token.value == ",":
                if message_buffer:
                    function_stack[-1]["messages"].append("".join(message_buffer))
                    message_buffer.clear()
                else:
                    function_stack[-1]["messages"].append(None)

        elif function_stack and token.type == "operator" and token.value == ")":
            function_stack.pop()

        if in_translator_comments and translator_comments[-1][0] < token.lineno:
            in_translator_comments = False

        last_token = token
