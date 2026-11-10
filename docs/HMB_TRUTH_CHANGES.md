# HMB truth.csv changes

`truth.csv` (the HMB dev set) lives with the plan PDF in `_incoming/plans`, outside git. Changes to it are recorded here.

## Nov 5, 2026: rooms 108, 109 and 112 (Jon approved)

| Room | Was | Now | Why |
|---|---|---|---|
| 108 Women's Restroom | 153.1 | 160.8 | Re-measured face to face on A101. The area between the wall faces is 12.41 x 12.60 ft, plus the accessible stall's 1.08 x 3.64 ft jog. Stalls and the floor under the vanity are counted, and doors are closed at the wall line. The round-2 value (12'-6" x 13'-4" less 13.6 SF) took off too much. |
| 109 Women's Shower | 129.8 | 133.2 | Jon (Nov 3, confirmed Nov 5): the floor under the shower benches counts. Measured face to face on A101 with both benches in. |
| 112 Women's Public Toilet Room | 248.0 | 270.3 | Re-measured face to face. The main room is 14.30 x 17.91 ft (256.1 SF). The D01 entry inside the exterior wall adds 5.43 x 2.61 ft (14.2 SF); Jon ruled that entry part of the room. |

### How the rooms were measured
- **Tools:** `tools/room_walls.py` makes the crops and lists the wall-layer lines. The measuring itself was done on wall-thick ink only, with doors closed at the wall line.
- **Second check:** the numbers have not been checked by a second person.
- **Backup:** the old file is in `backups/pre_truth_nov5/truth.csv` on the dev PC.

### Program fix made at the same time
`autotakeoff._bench_footprints`: a bench drawn with seat and lip lines inside its outline no longer reads as wall.

| Room | Before | After |
|---|---|---|
| 109 | 119.7 | 125.6 |
| 104 | 128.3 | 133.6 |
| 105 | 156.5 | 160.3 |

The other A101 rooms are unchanged. All nine rooms are within 8% of the new truths.
