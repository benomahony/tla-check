---- MODULE Counter ----
EXTENDS Naturals
VARIABLE count
Init == count = 0
Next == count' = Missing + 1
Spec == Init /\ [][Next]_count
====
