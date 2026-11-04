---- MODULE Counter ----
EXTENDS Naturals
VARIABLE count
Init == count = 0
Next == count < 3 /\ count' = count + 1
Spec == Init /\ [][Next]_count
TypeOK == count \in Nat
Small == count < 2
====
