CLASS z_humaneval_erp_006 DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC .

  PUBLIC SECTION.
    CLASS-METHODS: calculate_stock
      IMPORTING
        mat_id        TYPE char20
      RETURNING
        VALUE(rs_result) TYPE ztransaction.
  PROTECTED SECTION.
  PRIVATE SECTION.
ENDCLASS.

CLASS z_humaneval_erp_006 IMPLEMENTATION.

  METHOD calculate_stock.
  ENDMETHOD.


ENDCLASS.