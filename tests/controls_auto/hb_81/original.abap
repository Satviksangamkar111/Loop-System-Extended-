CLASS z_humaneval_081 DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC.

  PUBLIC SECTION.
    TYPES: BEGIN OF ty_grade,
             gpa TYPE f,
           END OF ty_grade.
    TYPES: tt_grades TYPE TABLE OF ty_grade.

    CLASS-METHODS: numerical_letter_grade
      IMPORTING
        grades               TYPE tt_grades
      RETURNING
        VALUE(letter_grades) TYPE string_table.
  PROTECTED SECTION.
  PRIVATE SECTION.
ENDCLASS.

CLASS z_humaneval_081 IMPLEMENTATION.

  METHOD numerical_letter_grade.
  ENDMETHOD.


ENDCLASS.