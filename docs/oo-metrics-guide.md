# OO Metrics Interpretation Guide

smellcheck computes five object-oriented metrics for every class that meets minimum size thresholds (SC801 requires at least 3 methods and 2 fields; SC805 requires at least 3 non-dunder methods). Each metric highlights a different structural risk. This guide explains what they measure, when they fire, and when it is safe to ignore them.

## SC801 — Lack of Cohesion of Methods (LCOM)

**What it measures:** How related the methods in a class are to each other, based on shared instance attribute usage. A value of 0 means every method touches the same attributes; a value of 1 means no methods share any attributes.

**Threshold:** > 0.8 (severity: warning)

**Before:**
```python
class Blob:
    def parse(self):
        self.data = read()

    def send_email(self):
        smtp.send(self.to)
```

**After:**
```python
class Parser:
    def parse(self):
        self.data = read()

class Mailer:
    def send_email(self):
        smtp.send(self.to)
```

**When to ignore:** Data-classes or DTOs with many independent fields but few methods. Classes that serve as namespaces for related but independent utility methods.

## SC802 — Coupling Between Objects (CBO)

**What it measures:** How many distinct external classes a given class references by name — counted by detecting attribute accesses on uppercase-named variables within method bodies (e.g. `Foo.bar`, `Bar.method`). High CBO means a change in any of those dependencies may force changes here too.

**Threshold:** > 8 (severity: warning)

**Before:**
```python
class Order:
    def process(self):
        Inventory.check(self.items)
        Payment.charge(self.total)
        Shipping.ship(self.address)
        Email.send(self.user)
        Logger.log(self.id)
```

**After:**
```python
class Order:
    def __init__(self, fulfillment: Fulfillment):
        self.fulfillment = fulfillment

    def process(self):
        self.fulfillment.run()
```

**When to ignore:** Facade or mediator classes that exist specifically to coordinate many collaborators. ORM model classes that reference many related models.

## SC803 — Excessive Fan-Out

**What it measures:** How many other modules within the same project a single module imports. This is a module-level metric based on outgoing import dependencies — not class-level coupling. A module with high fan-out is tightly coupled to the rest of the codebase and hard to extract or reuse.

**Threshold:** > 15 outgoing module imports (severity: info)

**Before:**
```python
# report.py
from .db import DB
from .cache import Cache
from .formatter import Fmt
from .mailer import Mail
from .logger import Log
# ... 10+ more imports
```

**After:**
```python
# report.py
from .report_facade import ReportFacade  # single dependency

class Report:
    def __init__(self, facade: ReportFacade):
        self.facade = facade

    def build(self):
        self.facade.generate()
```

**When to ignore:** Top-level composition roots or application entry points that wire dependencies together. Test setup modules that necessarily import many modules.

## SC804 — Response for a Class (RFC)

**What it measures:** The total number of methods that could potentially be executed in response to a message sent to the class — including its own methods plus methods it calls on other objects. High RFC means the class is hard to test and reason about.

**Threshold:** > 20 (severity: info)

**Before:**
```python
class Service:
    def create(self): ...
    def read(self): ...
    def update(self): ...
    def delete(self): ...
    def validate(self): ...
    def notify(self): ...
```

**After:**
```python
class Service:
    def create(self): ...
    def read(self): ...

class Validator:
    def validate(self): ...

class Notifier:
    def notify(self): ...
```

**When to ignore:** Classes that implement a large interface contract (e.g. a REST resource with many endpoints). Abstract base classes that define many hook methods.

## SC805 — Remove Middle Man

**What it measures:** The percentage of methods in a class that do nothing but delegate to another object. When more than half the methods are pure delegation, the class adds indirection without value.

**Threshold:** > 50% delegation ratio (severity: info)

**Before:**
```python
class Proxy:
    def __init__(self, real):
        self.real = real

    def do(self):
        return self.real.do()

    def run(self):
        return self.real.run()
```

**After:**
```python
# Call the real object directly — no middleman needed
obj = Real()
obj.do()
obj.run()
```

**When to ignore:** Intentional proxies, adapters, or decorators that add cross-cutting concerns (logging, caching, access control). Wrapper classes that provide a simplified API over a complex dependency.

## Summary Table

| Code  | Metric | Threshold | Severity | Key Question |
|-------|--------|-----------|----------|--------------|
| SC801 | LCOM   | > 0.8     | warning  | Are the methods in this class related? |
| SC802 | CBO    | > 8       | warning  | Does this class depend on too many others? |
| SC803 | Fan-Out | > 15     | info     | Does this class reach out to too many modules? |
| SC804 | RFC    | > 20      | info     | Could too many methods fire from one call? |
| SC805 | Middle Man | > 50% | info     | Is this class just passing calls through? |
