Implement an abap class with a static method that checks if the employee hierarchy is valid. 
The method should:
- Read all entries from ZORG_STRUCTURE.
- Return abap_true if the organizational structure satisfies all of the following:
   - Each employee has at most one direct manager.
   - There are no cycles in the manager relationships.
   - There is exactly one top-level manager (a "CEO") without a manager.
   - All employees are directly or indirectly connected to the CEO.
- Return abap_false otherwise.
Use this table: 
define table zorg_structure {
    key employee_id   : abap.char(20) not null;
    key supervisor_id : abap.char(20) not null;
}

Example:
Input:
DATA(zorg_entries) = VALUE zorg_structure ( 
  ( employee_id = 'A' superior_id = 'B' )
  ( employee_id = 'B' superior_id = 'C' )
  ( employee_id = 'C' superior_id = 'D' )
)
INSERT zorg_structure FROM TABLE @zorg_structure.
Output:
DATA(result) = zcl_hierarchy_utils=>is_valid_hierarchy( ).
" result = abap_true.

TARGET: implement this in the ABAP class Z_HUMANEVAL_ERP_004 in the given file. Its public section is already correct and must stay as it is: the methods there are the ones to implement, their bodies are empty now. Private helper methods may be added. If the text above is written in another language or names another class or method, its behaviour is what counts.
