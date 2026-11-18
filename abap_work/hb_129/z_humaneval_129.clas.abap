CLASS z_humaneval_129 DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC .

  PUBLIC SECTION.
    TYPES: BEGIN OF ty_grid_row,
             values TYPE int4_table,
           END OF ty_grid_row,
           ty_grid TYPE TABLE OF ty_grid_row.

    CLASS-METHODS: minpath
      IMPORTING
        grid          TYPE ty_grid
        k             TYPE i
      RETURNING
        VALUE(result) TYPE int4_table.
  PROTECTED SECTION.
  PRIVATE SECTION.
ENDCLASS.

CLASS z_humaneval_129 IMPLEMENTATION.

  METHOD minpath.
  ENDMETHOD.


ENDCLASS.