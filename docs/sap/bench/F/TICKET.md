# Fix indent of `<pre>` tags in HTML

- KNOWN: The file is src/ui/core/zcl_abapgit_html.clas.abap (abapGit, class ZCL_ABAPGIT_HTML).
- KNOWN: `<pre>...</pre>` sections do not render correctly since the HTML is indented, which leads to extra whitespace.
- KNOWN: abapGit is not impacted but tooling on top of abapGit is.
