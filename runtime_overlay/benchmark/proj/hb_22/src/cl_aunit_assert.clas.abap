CLASS cl_aunit_assert DEFINITION PUBLIC CREATE PUBLIC.
  PUBLIC SECTION.
    CLASS-METHODS assert_equals
      IMPORTING act TYPE any
                exp TYPE any
                msg TYPE csequence OPTIONAL.
ENDCLASS.

CLASS cl_aunit_assert IMPLEMENTATION.
  METHOD assert_equals.
    cl_abap_unit_assert=>assert_equals( act = act exp = exp msg = msg ).
  ENDMETHOD.
ENDCLASS.
