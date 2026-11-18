CLASS zcl_abapgit_progress DEFINITION LOCAL FRIENDS ltcl_calc_pct.

CLASS ltcl_calc_pct DEFINITION FINAL FOR TESTING
  DURATION SHORT
  RISK LEVEL HARMLESS.

  PRIVATE SECTION.
    DATA mv_act TYPE i.

    METHODS:
      zero_total_current_one FOR TESTING RAISING cx_static_check,
      zero_total_current_zero_no_dump FOR TESTING RAISING cx_static_check,
      zero_total_current_large FOR TESTING RAISING cx_static_check,
      half_is_50 FOR TESTING RAISING cx_static_check,
      one_of_three_is_33 FOR TESTING RAISING cx_static_check,
      two_of_three_is_67 FOR TESTING RAISING cx_static_check,
      full_is_99 FOR TESTING RAISING cx_static_check,
      zero_current_is_1 FOR TESTING RAISING cx_static_check,
      above_total_unchanged FOR TESTING RAISING cx_static_check,
      new_total_after_zero FOR TESTING RAISING cx_static_check,
      calc
        IMPORTING
          iv_total   TYPE i
          iv_current TYPE i.

ENDCLASS.


CLASS ltcl_calc_pct IMPLEMENTATION.

  METHOD calc.

    DATA li_progress TYPE REF TO zif_abapgit_progress.
    DATA lo_progress TYPE REF TO zcl_abapgit_progress.

    li_progress = zcl_abapgit_progress=>get_instance( iv_total ).
    lo_progress ?= li_progress.
    mv_act = lo_progress->calc_pct( iv_current = iv_current ).

  ENDMETHOD.

  METHOD zero_total_current_one.

    calc( iv_total = 0 iv_current = 1 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 0 ).

  ENDMETHOD.

  METHOD zero_total_current_zero_no_dump.

    " 0 of 0 does not raise today (the division 0 / 0 is defined as 0, so the 0->1 rule applies); only "no dump, sane value" is asserted
    calc( iv_total = 0 iv_current = 0 ).
    IF mv_act <> 0 AND mv_act <> 1.
      cl_abap_unit_assert=>fail( ).
    ENDIF.

  ENDMETHOD.

  METHOD zero_total_current_large.

    calc( iv_total = 0 iv_current = 5 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 0 ).

  ENDMETHOD.

  METHOD half_is_50.

    calc( iv_total = 100 iv_current = 50 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 50 ).

  ENDMETHOD.

  METHOD one_of_three_is_33.

    calc( iv_total = 3 iv_current = 1 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 33 ).

  ENDMETHOD.

  METHOD two_of_three_is_67.

    calc( iv_total = 3 iv_current = 2 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 67 ).

  ENDMETHOD.

  METHOD full_is_99.

    calc( iv_total = 100 iv_current = 100 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 99 ).
    calc( iv_total = 3 iv_current = 3 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 99 ).

  ENDMETHOD.

  METHOD zero_current_is_1.

    calc( iv_total = 100 iv_current = 0 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 1 ).
    calc( iv_total = 1000 iv_current = 1 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 1 ).

  ENDMETHOD.

  METHOD above_total_unchanged.

    calc( iv_total = 100 iv_current = 150 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 150 ).

  ENDMETHOD.

  METHOD new_total_after_zero.

    calc( iv_total = 0 iv_current = 1 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 0 ).
    calc( iv_total = 10 iv_current = 5 ).
    cl_abap_unit_assert=>assert_equals( act = mv_act exp = 50 ).

  ENDMETHOD.

ENDCLASS.
