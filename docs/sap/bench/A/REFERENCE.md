# REFERENCE (offline ABAP knowledge, selected for this job)
Reference only: the SPEC and the locked tests decide what is correct.

## cheat-sheets/28_Regular_Expressions.md > Escaped Characters and Special Variants


Note that some of the example strings are represented by string templates.

| Expression | Represents | Example Regex | Example String | Matches | Does not Match |
|---|---|---|---|---|---|
| `\...` | To include special characters like `[] \ / ^`, use `\` to escape them. Use `\.` to match a period ("."). | `.\.` | ab.cd.ef |  a<ins>**b.**</ins>c<ins>**d.**</ins>ef | ab<ins>**.c**</ins>d<ins>**.e**</ins>f |
| `\n` | Line feed (negation `\N` for non-line feeds) | `\n\D` | <code>\|\nabc\n123\|</code> | <code>\|\na\|</code> | <code>\|\n1\|</code> |
| `\t` | Tab | `\t\d` | <code>\|\tabc\t123\|</code> | <code>\|\t1\|</code> | <code>\|\ta\|</code> |
| `\r` | Carriage return | `\r\s` | <code>\|\rabc\r 123\|</code> | <code>\|\r \|</code> | <code>\|\ra\|</code> |
| `\R` | Line feed sequence, ensuring that regular expression matches all kinds of newlines, such as `\n`, `\r`, or `\r\n` (carriage return followed by line feed)  | `\R.` | <code>\|abc\rdef\nghi\r\njkl mno\|</code> | <code>\|\rd\|</code>, <code>\|\ng\|</code>, <code>\|\r\nj\|</code> | <code>\| m\|</code> |
| `\x{...}` | Character with hex code | `\x{00A0}#` (non-breaking space and #) | <code>\|#{ cl_abap_conv_codepage=>create_in( codepage = \`UTF-16BE\` )->convert( source = CONV xstring( \`00A0\` ) ) }#\|</code> | The non-breaking space plus the second # character | The first # character |
| `\N{U+...}` | Character with Unicode code point | `\N{U+00A0}#` (non-breaking space and # as above) | See the example below | See the example below | |
| `\p{..}` | Character with a specified Unicode character property; see the [documentation](https://help.sap.com/docs/abap-cloud/abap-keyword/pcre-regex-special-characters) for options; among them, there are, for example, properties for lowercase (`Ll`) and uppercase (`Lu`) letters; negation: `\P{..}` | 1. `\p{Ll}+` <br> 2. `\p{Lu}+` <br> 3. `\P{Lu}+`  | Hello ABAP | 1. H<ins>**ello**</ins> ABAP <br> 2. <ins>**H**</ins>ello <ins>**ABAP**</ins> <br> 3. H<ins>**ello&nbsp;**</u></ins>ABAP (the space is also matched) | 1. Upper case letter sequences <br> 2. Lower case letter sequences <br> 3. Upper case letter sequences |

Examples:


DATA string_esc_chars TYPE string.

"Special characters
"a#b#c#d#e#f#g
string_esc_chars = replace( val = `a[b]c\d/e^f.g` pcre = `\[|\]|\\|\/|\^|\.` with = `#` occ = 0 ).

"Line feeds
"a#b#c
string_esc_chars = replace( val = |a\nb\nc| pcre = `\n` with = `#` occ = 0 ).

"Line feed negation
"String template representation of the result: |#\n#\n#|
string_esc_chars = replace( val = |a\nb\nc| pcre = `\N` with = `#` occ = 0 ).

"Tabs
"a#b#c
string_esc_chars = replace( val = |a\tb\tc| pcre = `\t` with = `#` occ = 0 ).

"Carriage return
"d#e#f
string_esc_chars = replace( val = |d\re\rf| pcre = `\r` with = `#` occ = 0 ).

"Characters with hex code
"The example string includes a non-breaking space.
"#x#
string_esc_chars = replace( 
  val = |#{ cl_abap_conv_codepage=>create_in( codepage = `UTF-16BE` )->convert( source = CONV xstring( `00A0` ) ) }#|
  pcre = `\x{00A0}` with = `x` occ = 0 ).

"Characters with Unicode code point
"As above, the example string includes a non-breaking space.
"The PCRE syntax uses the control verb (*UTF) to enable UTF mode.
"#y#
string_esc_chars = replace( 
  val = |#{ cl_abap_conv_codepage=>create_in( codepage = `UTF-16BE` )->convert( source = CONV xstring( `00A0` ) ) }#|
  pcre = `(*UTF)\N{U+00A0}` with = `y` occ = 0 ).

"Characters with a specified Unicode character property
"H# ABAP
string_esc_chars = replace( val = `Hello ABAP` pcre = `\p{Ll}+` with = `#` occ = 0 ).

"#ello #
string_esc_chars = replace( val = `Hello ABAP` pcre = `\p{Lu}+` with = `#` occ = 0 ).

"#ello#
string_esc_chars = replace( val = `Hello ABAP` pcre = `\P{Ll}+` with = `#` occ = 0 ).

"H#ABAP
string_esc_chars = replace( val = `Hello ABAP` pcre = `\P{Lu}+` with = `#` occ = 0 ).

<p align="right"><a href="#top">⬆️ back to top</a></p>

## cheat-sheets/28_Regular_Expressions.md > Setting Options and Control Verbs


There are various [setting options](https://help.sap.com/docs/abap-cloud/abap-keyword/pcre-regex-special-characters) for specifying PCRE syntax. The following examples demonstrate a selection:

*Multi- and single-line modes*
- `(?m)` enables multi-line mode.
- `(?s)` enables single-line mode.
- Note in this context:
  - The `.` character does not match new lines unless single-line mode is set.
  - The anchors `^` and `$` become especially relevant in multi-line mode.
  - These settings apply to the subsequent part of the group in which they are specified, such as the top-level pattern or a capturing group.


Examples:


DATA string_opt_set TYPE string.

"----------- Examples with `.` and single line mode -----------

"`.` matches new lines feeds when the single line option is set
"Result (9 replacements):
"###
"###
"###
string_opt_set = replace( val = |abc\ndef\nghi| pcre = `.` with = `#` occ = 0 ).

"Result (11 replacements including the new line feeds):
"###########
string_opt_set = replace( val = |abc\ndef\nghi| pcre = `(?s).` with = `#` occ = 0 ).

"##
string_opt_set = replace( val = |\n\n| pcre = `(?s).` with = `#` occ = 0 ).

"----------- Examples for the start of subjects -----------

"Multi-line mode not enabled
"Result:
"#bc
"def
"ghi
string_opt_set = replace( val = |abc\ndef\nghi| pcre = `^.` with = `#` occ = 0 ).

"Multi-line mode enabled
"Result:
"#bc
"#ef
"#hi
string_opt_set = replace( val = |abc\ndef\nghi| pcre = `(?m)^.` with = `#` occ = 0 ).

"\A for comparison
"Result:
"#bc
"def
"ghi
string_opt_set = replace( val = |abc\ndef\nghi| pcre = `(?m)\A.` with = `#` occ = 0 ).

"----------- Examples for the end of subjects -----------

"Result:
"abc
"def
"gh#
string_opt_set = replace( val = |abc\ndef\nghi| pcre = `.$` with = `#` occ = 0 ).

"Result:
"ab#
"de#
"gh#
string_opt_set = replace( val = |abc\ndef\nghi| pcre = `(?m).$` with = `#` occ = 0 ).

"\Z syntax (the result is the same as with `.$`)
string_opt_set = replace( val = |abc\ndef\nghi| pcre = `(?m).\Z` with = `#` occ = 0 ).

*Extended Mode*

- Regular expressions with PCRE can be processed in normal or extended mode.
- In extended mode, unescaped whitespaces in the pattern are ignored.
- The extended mode is the default for ABAP statements and built-in functions, but you can disable it in the regex pattern with `(?-x)`. The `create_pcre` method of the `CL_ABAP_REGEX` class includes an `extended` parameter for this purpose.
- To handle whitespaces in regular expressions, escape it with `\ `, match it using `\s`, or disable extended mode with `(?-x)`.

The following code snippet shows the extended mode enabled by default and then explicitly disabled in a PCRE regular expression.


DATA some_string TYPE string.

"Extended mode is enabled by default
"No replacement in the example.
"Result: abc def
some_string = replace( val = `abc def` pcre = `abc def` with = `#` ).

"The following example works because there is no whitespace in the source string.
"The whitespace in the regular expression is ignored.
"Result: #
some_string = replace( val = `abcdef` pcre = `abc def` with = `#` ).

"To match whitespace characters, you can use the pattern \s
"Result: #
some_string = replace( val = `abc def` pcre = `abc\sdef` with = `#` ).

"Escaping a whitespace using \
"Result: #
some_string = replace( val = `abc def` pcre = `abc\ def` with = `#` ).
"The following example also performs the replacement as the unescaped whitespaces
"are ignored.
some_string = replace( val = `abc def` pcre = `abc\         def` with = `#` ).

"Disabling the extended mode so that whitespaces are not ignored
"Result: #
some_string = replace( val = `abc def` pcre = `(?-x)abc def` with = `#` ).

*Control verbs*

Control verbs, for example, for ...

- enabling UTF mode using `(*UTF)`. In PCRE syntax, you can define UTF-16 character strings.
- line breaks such as the following:
  - `(*CR)`: Only carriage returns
  - `(*LF)`	Only line feed
  - `(*CRLF)`: Only carriage returns followed by a line feed
  - `(*ANYCRLF)`: All of the above-mentioned options


DATA ctrl_verb_string TYPE string.

"Using (*UTF); the source string contains a non-breakable space that is to be replaced
"Result: #x#
ctrl_verb_string = replace( 
  val = |#{ cl_abap_conv_codepage=>create_in( codepage = `UTF-16BE` )->convert( source = CONV xstring( `00A0` ) ) }#|
  pcre = `(*UTF)\N{U+00A0}` with = `x` occ = 0 ).

"Line breaks
"The results are demonstrated using string templates.
"In the examples, the multi-line mode is enabled in addition.

"|_abc\ndef\r_ghi\r_\njkl|
ctrl_verb_string = replace( val = |abc\ndef\rghi\r\njkl|
                            pcre = `(*CR)(?m)^` with = `_` occ = 0 ).

ctrl_verb_string = replace( val = |abc\ndef\rghi\r\njkl|
                            pcre = `(*LF)(?m)^` with = `_` occ = 0 ).

"|_abc\n_def\rghi\r\n_jkl|
ctrl_verb_string = replace( val = |abc\ndef\rghi\r\njkl|
                            pcre = `(*CRLF)(?m)^` with = `_` occ = 0 ).

"|_abc\n_def\r_ghi\r\n_jkl|
ctrl_verb_string = replace( val = |abc\ndef\rghi\r\njkl|
                            pcre = `(*ANYCRLF)(?m)^` with = `_` occ = 0 ).


<p align="right"><a href="#top">⬆️ back to top</a></p>

## cheat-sheets/07_String_Processing.md > Control Characters in String Templates

- String templates interpret certain character combinations as [control
characters](https://help.sap.com/docs/abap-cloud/abap-keyword/string-tmpl-control-characters).
- For example, `\n` is interpreted as a newline. A new line is
started. 

The following syntax examples demonstrate a selection:
"\n is interpreted as a line feed
DATA(s1) = `Hello`.
DATA(s2) = `World`.
DATA(s3) = |{ s1 }\n{ s2 }\nHow are you\n?|.

*Hello
*World
*How are you
*?

"Excursion: The CL_ABAP_CHAR_UTILITIES class provides attributes and methods as utilities for string processing.
"The following examples demonstrate that attributes that contain control characters can be replaced by
"a representation of control characters in a string template.
ASSERT cl_abap_char_utilities=>newline        = |\n|.
ASSERT cl_abap_char_utilities=>horizontal_tab = |\t|.
ASSERT cl_abap_char_utilities=>cr_lf          = |\r\n|.

<p align="right"><a href="#top">⬆️ back to top</a></p>
