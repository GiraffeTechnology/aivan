# Lead-time response semantics

Aivan consumes lead-time results from GLTG. It does not replace missing provider
facts with a local delivery calculation.

- Day values retain fractional precision in supplier replies, GLTG estimates and
  RFQ simulations. A fractional confidence estimate is compared with the deadline
  without first rounding down.
- P50 is the expected quantile, not the earliest possible delivery. The earliest
  or minimum field is nullable when the provider does not supply that evidence.
  A supplied zero remains zero.
- Missing component durations and critical paths remain absent. Returned
  component durations retain their precision.
- Deadline feasibility is a boolean or unknown (`null`). Aivan preserves these
  three states and rejects malformed values rather than applying truth coercion.

The synthetic consumer tests verify mapping and cutoff behavior. They do not
establish model accuracy, live provider availability, private-data persistence,
or a complete deployed workflow. Model calculation and evaluation remain GLTG's
responsibility.
