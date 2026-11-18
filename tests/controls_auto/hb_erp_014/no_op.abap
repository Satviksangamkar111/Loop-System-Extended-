CLASS z_humaneval_erp_014 DEFINITION FINAL PUBLIC.
  PUBLIC SECTION.
    CLASS-METHODS: count_bookings_for_flight
      IMPORTING
        iv_carrid       TYPE char3
        iv_connid       TYPE numc4
        iv_fldate       TYPE dats
      RETURNING
        VALUE(rv_count) TYPE i.
  PROTECTED SECTION.
  PRIVATE SECTION.
ENDCLASS.

CLASS z_humaneval_erp_014 IMPLEMENTATION.
  METHOD count_bookings_for_flight.
  ENDMETHOD.

ENDCLASS.