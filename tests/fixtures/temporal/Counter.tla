---- MODULE Counter ----
EXTENDS Naturals
VARIABLE count
Init == count = 0
Next == (count < 3 /\ count' = count + 1) \/ (count = 3 /\ UNCHANGED count)
Spec == Init /\ [][Next]_count
Reaches == <>(count = 3)
====
