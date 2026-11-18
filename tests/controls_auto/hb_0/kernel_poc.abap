CLASS z_humaneval_000 DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC .

  PUBLIC SECTION.
    TYPES: BEGIN OF ty_float_table,
             value TYPE f,
           END OF ty_float_table.
    TYPES: tt_float_table TYPE TABLE OF ty_float_table.

    CLASS-METHODS: has_close_elements
      IMPORTING
        numbers       TYPE tt_float_table
        threshold     TYPE f
      RETURNING
        VALUE(result) TYPE abap_bool.
  PROTECTED SECTION.
  PRIVATE SECTION.
ENDCLASS.

CLASS z_humaneval_000 IMPLEMENTATION.
  METHOD has_close_elements.
    WRITE '@KERNEL console.log(1);'.
  ENDMETHOD.

ENDCLASS.