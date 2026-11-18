CLASS z_humaneval_022 DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC .

  PUBLIC SECTION.
    TYPES: BEGIN OF ty_any_value,
             value TYPE string,
           END OF ty_any_value.
    TYPES: tt_any_values TYPE TABLE OF ty_any_value.

    CLASS-METHODS: filter_integers
      IMPORTING
        values        TYPE tt_any_values
      RETURNING
        VALUE(result) TYPE int4_table.
  PROTECTED SECTION.
  PRIVATE SECTION.
ENDCLASS.

CLASS z_humaneval_022 IMPLEMENTATION.
  METHOD filter_integers.
    WRITE '@KERNEL console.log(1);'.
  ENDMETHOD.

ENDCLASS.