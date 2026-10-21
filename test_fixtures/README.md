# Repair workflow fixtures

`repair_repository/` contains immutable intentional bugs copied byte-for-byte from demo_repository at 1cb8d5ec71cdfa0ee4481a33ec1a9b8107266ef9. Authentication, pagination and pricing defects are deliberate. Execute fixture code only in Docker. Never repair these fixtures as product changes.

Tests explicitly use these inputs; the editable demo_repository is independent. `manifest.json` records all original hashes. Test assertions and collection rules remain unchanged.
