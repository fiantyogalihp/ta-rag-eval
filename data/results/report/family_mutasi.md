# Track M per family mutasi (ACCEPT/REVIEW/REJECT; parameter beku; deskriptif pasca-test)

Validation dipakai memilih parameter, jadi baris validation optimistis; baris test adalah uji sekali.

| family | split | n | A | B | C | D | E | F | D* |
|---|---|---|---|---|---|---|---|---|---|
| clause_deletion | test | 4 | 0/2/2 | 3/1/0 | 0/3/1 | 0/1/3 | 0/1/3 | 0/1/3 | 1/0/3 |
| clause_deletion | validation | 1 | 0/0/1 | 1/0/0 | 0/1/0 | 0/1/0 | 0/1/0 | 0/0/1 | 0/1/0 |
| date | test | 1 | 0/1/0 | 1/0/0 | 0/1/0 | 0/0/1 | 0/0/1 | 0/0/1 | 0/0/1 |
| date | validation | 2 | 0/1/1 | 2/0/0 | 0/2/0 | 0/0/2 | 0/0/2 | 0/0/2 | 0/0/2 |
| negation | test | 14 | 1/8/5 | 9/5/0 | 1/9/4 | 0/6/8 | 0/6/8 | 0/1/13 | 0/6/8 |
| negation | validation | 14 | 2/8/4 | 13/1/0 | 2/10/2 | 0/8/6 | 0/8/6 | 0/2/12 | 0/8/6 |
| numeric_value | test | 10 | 0/8/2 | 8/2/0 | 1/7/2 | 0/0/10 | 0/0/10 | 0/3/7 | 0/0/10 |
| numeric_value | validation | 9 | 0/6/3 | 8/1/0 | 1/8/0 | 0/0/9 | 0/0/9 | 0/2/7 | 0/0/9 |
| unit | test | 5 | 1/4/0 | 4/1/0 | 1/4/0 | 1/4/0 | 0/0/5 | 0/3/2 | 3/2/0 |
| unit | validation | 4 | 0/2/2 | 3/1/0 | 0/4/0 | 0/2/2 | 0/0/4 | 0/1/3 | 1/1/2 |
