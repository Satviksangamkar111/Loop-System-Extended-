CLASS z_humaneval_020 DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC.

  PUBLIC SECTION.
    TYPES: BEGIN OF ty_number,
             value TYPE f,
           END OF ty_number.
    TYPES: tt_numbers TYPE STANDARD TABLE OF ty_number.
    TYPES: tt_result TYPE SORTED TABLE OF f WITH UNIQUE KEY table_line.

    CLASS-METHODS: find_closest_elements
      IMPORTING
        VALUE(numbers)      TYPE tt_numbers
      RETURNING
        VALUE(closest_pair) TYPE tt_result.
  PROTECTED SECTION.
  PRIVATE SECTION.
ENDCLASS.

CLASS z_humaneval_020 IMPLEMENTATION.

  METHOD find_closest_elements.
  ENDMETHOD.


ENDCLASS.