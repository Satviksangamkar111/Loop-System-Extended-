CLASS z_humaneval_104 DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC .

  PUBLIC SECTION.
    TYPES: BEGIN OF ty_int_table,
             value TYPE i,
           END OF ty_int_table,
           tt_int_table TYPE STANDARD TABLE OF ty_int_table WITH NON-UNIQUE DEFAULT KEY.

    CLASS-METHODS: unique_digits
      IMPORTING
        VALUE(x)      TYPE tt_int_table
      RETURNING
        VALUE(result) TYPE tt_int_table.
  PROTECTED SECTION.
  PRIVATE SECTION.
ENDCLASS.

CLASS z_humaneval_104 IMPLEMENTATION.

  METHOD unique_digits.
  ENDMETHOD.


ENDCLASS.