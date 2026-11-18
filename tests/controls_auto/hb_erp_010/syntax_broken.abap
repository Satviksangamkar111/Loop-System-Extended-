CLASS z_humaneval_erp_010 DEFINITION
  PUBLIC
  FINAL
  CREATE PUBLIC .

  PUBLIC SECTION.
    TYPES:
      tt_customer_records TYPE STANDARD TABLE OF zcustomer WITH EMPTY KEY .

    CLASS-METHODS find_by_pattern
      IMPORTING
        iv_pattern        TYPE string
      RETURNING
        VALUE(rt_results) TYPE tt_customer_records.
  PROTECTED SECTION.
  PRIVATE SECTION.
ENDCLASS.

CLASS z_humaneval_erp_010 IMPLEMENTATION.

  METHOD find_by_pattern.
    THIS IS NOT ABAP AT ALL.
  ENDMETHOD.


ENDCLASS.