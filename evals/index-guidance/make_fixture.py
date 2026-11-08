"""Make the fixtures of the guidance.index eval (D107): `shop` (228 files) and `market` (624 files).

Usage: python3 make_fixture.py [<fixtures folder>]. The default is `fixtures` next to this file.
The script deletes `shop` and `market` in that folder first, and the output is the same on each
run. Each entity gets 5 Python, 5 TypeScript, and 5 JavaScript files. The entities share a few
common names (`load`, `save`, `Store`), as in a real repo. `shop` has 14 entities, and PLANTS has
the facts of the X scenarios. `market` has 40 entities, PLANTS, and MARKET_PLANTS: the facts of the
M scenarios, which each need code from 3 files or more.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ENTITIES = ("order", "invoice", "customer", "product", "shipment", "payment", "refund", "coupon",
            "warehouse", "supplier", "review", "cart", "wishlist", "notification")
MARKET_ENTITIES = ENTITIES + (
    "ledger", "payout", "subscription", "vendor", "tax", "region", "carrier", "label", "promotion",
    "bundle", "gift", "loyalty", "ticket", "survey", "banner", "page", "menu", "session", "account",
    "address", "plan", "quote", "receipt", "rate", "station", "batch")

PY = {
    "api/shopapi/models/{e}.py": '''"""The {E} record of the shop API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from shopapi.core.ids import new_id

STATUSES = ("new", "active", "closed")


@dataclass
class {E}:
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "new"
    amount: int = 0
    notes: str = ""

    def validate(self) -> list[str]:
        problems = []
        if not self.id:
            problems.append("{e} has no id")
        if self.status not in STATUSES:
            problems.append(f"{e} status {self.status} is not known")
        if self.amount < 0:
            problems.append("{e} amount is below zero")
        return problems

    def to_dict(self) -> dict:
        return {"id": self.id, "status": self.status, "amount": self.amount,
                "notes": self.notes, "created_at": self.created_at.isoformat()}
''',
    "api/shopapi/repo/{e}_repo.py": '''"""Storage of {E} records."""

from __future__ import annotations

from shopapi.core.db import Database
from shopapi.models.{e} import {E}


class {E}Repo:
    table = "{e}s"

    def __init__(self, db: Database) -> None:
        self.db = db

    def load(self, item_id: str) -> {E} | None:
        row = self.db.fetch_one(self.table, item_id)
        return {E}(**row) if row else None

    def save(self, item: {E}) -> None:
        problems = item.validate()
        if problems:
            raise ValueError("; ".join(problems))
        self.db.upsert(self.table, item.to_dict())

    def delete(self, item_id: str) -> None:
        self.db.delete(self.table, item_id)

    def list_open(self) -> list[{E}]:
        return [{E}(**row) for row in self.db.fetch_all(self.table) if row["status"] != "closed"]
''',
    "api/shopapi/services/{e}_service.py": '''"""Business rules for {e} records."""

from __future__ import annotations

from shopapi.models.{e} import {E}
from shopapi.repo.{e}_repo import {E}Repo
{IMPORTS}

class {E}Service:
    def __init__(self, repo: {E}Repo) -> None:
        self.repo = repo

    def create(self, amount: int = 0, notes: str = "") -> {E}:
        item = {E}(amount=amount, notes=notes)
        self.repo.save(item)
        return item

    def close(self, item_id: str) -> None:
        item = self.repo.load(item_id)
        if item is None:
            raise KeyError(item_id)
        item.status = "closed"
        self.repo.save(item)

    def find_open(self) -> list[{E}]:
        return self.repo.list_open()
{EXTRA}''',
    "api/shopapi/handlers/{e}_handler.py": '''"""HTTP handlers for {e} records."""

from __future__ import annotations

from shopapi.core.http import Request, Response
from shopapi.services.{e}_service import {E}Service
{IMPORTS}

def handle_get(service: {E}Service, request: Request) -> Response:
    item = service.repo.load(request.params["id"])
    if item is None:
        return Response(404, {"error": "{e} not found"})
    return Response(200, item.to_dict())


def handle_post(service: {E}Service, request: Request) -> Response:
    item = service.create(amount=int(request.body.get("amount", 0)))
    return Response(201, item.to_dict())


def register(router, service: {E}Service) -> None:
    router.add("GET", "/{e}s/<id>", lambda request: handle_get(service, request))
    router.add("POST", "/{e}s", lambda request: handle_post(service, request))
{EXTRA}''',
    "api/tests/test_{e}.py": '''import unittest

from shopapi.models.{e} import {E}


class {E}Test(unittest.TestCase):
    def test_new_{e}_is_valid(self):
        self.assertEqual({E}(amount=5).validate(), [])

    def test_negative_amount_is_a_problem(self):
        self.assertTrue({E}(amount=-1).validate())


if __name__ == "__main__":
    unittest.main()
''',
}

TS = {
    "web/src/types/{e}.ts": '''export interface {E}Row {
  id: string;
  status: "new" | "active" | "closed";
  amount: number;
  notes: string;
  createdAt: string;
}

export type {E}Status = {E}Row["status"];

export const EMPTY_{U}: {E}Row = { id: "", status: "new", amount: 0, notes: "", createdAt: "" };
''',
    "web/src/api/{e}Api.ts": '''import { http } from "../lib/http";
import type { {E}Row } from "../types/{e}";

export async function fetch{E}(id: string): Promise<{E}Row> {
  return http.get(`/{e}s/${id}`);
}

export async function list{E}s(): Promise<{E}Row[]> {
  return http.get("/{e}s");
}

export async function save{E}(row: {E}Row): Promise<void> {
  await http.post("/{e}s", row);
}
{EXTRA}''',
    "web/src/stores/{e}Store.ts": '''import { fetch{E}, list{E}s, save{E} } from "../api/{e}Api";
import type { {E}Row } from "../types/{e}";
{IMPORTS}
export class {E}Store {
  rows: {E}Row[] = [];
  loading = false;

  async load(): Promise<void> {
    this.loading = true;
    this.rows = await list{E}s();
    this.loading = false;
  }

  async refresh(id: string): Promise<void> {
    const row = await fetch{E}(id);
    this.rows = this.rows.map((r) => (r.id === id ? row : r));
  }

  async save(row: {E}Row): Promise<void> {
    await save{E}(row);
    await this.load();
  }
{EXTRA}}
''',
    "web/src/components/{E}List.tsx": '''import { formatMoney } from "../lib/format";
import { {E}Store } from "../stores/{e}Store";
import type { {E}Row } from "../types/{e}";

export function {E}List({ store }: { store: {E}Store }) {
  return (
    <ul>
      {store.rows.map((row: {E}Row) => (
        <li key={row.id}>
          {row.id} {row.status} {formatMoney(row.amount)}
        </li>
      ))}
    </ul>
  );
}
''',
    "web/src/components/{E}Form.tsx": '''import { formatMoney } from "../lib/format";
import { {E}Store } from "../stores/{e}Store";
import { EMPTY_{U}, type {E}Row } from "../types/{e}";

export function {E}Form({ store, row = EMPTY_{U} }: { store: {E}Store; row?: {E}Row }) {
  const submit = () => store.save({ ...row, status: "active" });
  return (
    <form onSubmit={submit}>
      <label>Amount: {formatMoney(row.amount)}</label>
      <textarea defaultValue={row.notes} />
      <button type="submit">Save</button>
    </form>
  );
}
''',
}

JS = {
    "tools/{e}/seed.js": '''const { log } = require("../lib/log");
const { connect } = require("../lib/db");

async function seed{E}s(count) {
  const db = await connect();
  for (let i = 0; i < count; i += 1) {
    await db.insert("{e}s", { id: `{e}-${i}`, status: "new", amount: i * 100 });
  }
  log(`seeded ${count} {e}s`);
}

module.exports = { seed{E}s };
''',
    "tools/{e}/migrate.js": '''const { log } = require("../lib/log");
const { connect } = require("../lib/db");
{IMPORTS}
async function migrate{E}s() {
  const db = await connect();
  const rows = await db.all("{e}s");
  for (const row of rows) {
    if (row.state !== undefined) {
      await db.update("{e}s", row.id, { status: row.state, state: undefined });
    }
  }
  log(`migrated ${rows.length} {e}s`);
}
{EXTRA}
module.exports = { migrate{E}s{EXPORTS} };
''',
    "tools/{e}/report.js": '''const { log } = require("../lib/log");
const { connect } = require("../lib/db");
{IMPORTS}
async function report{E}s() {
  const db = await connect();
  const rows = await db.all("{e}s");
  const total = rows.reduce((sum, row) => sum + row.amount, 0);
  log(`{e}s: ${rows.length}, total ${total}`);{CALLS}
  return { count: rows.length, total };
}

module.exports = { report{E}s };
''',
    "tools/{e}/index.js": '''const { seed{E}s } = require("./seed");
const { migrate{E}s{EXPORTS} } = require("./migrate");
const { report{E}s } = require("./report");

async function main(argv) {
  const command = argv[2];
  if (command === "seed") return seed{E}s(Number(argv[3] || 10));
  if (command === "migrate") {
    await migrate{E}s();{CALLS}
    return undefined;
  }
  if (command === "report") return report{E}s();
{COMMANDS}  throw new Error(`unknown command: ${command}`);
}

module.exports = { main };
''',
    "web/legacy/{e}.js": '''// The {e} page of the old web app. The new app uses web/src/stores/{e}Store.ts.
export function load(id) {
  return fetch(`/{e}s/${id}`).then((response) => response.json());
}

export function save(row) {
  return fetch("/{e}s", { method: "POST", body: JSON.stringify(row) });
}
''',
}

# The facts that the scenarios ask about: (file template, entity) -> the text for each slot.
PLANTS = {
    ("api/shopapi/services/{e}_service.py", "customer"): {"EXTRA": '''
    def apply_loyalty_discount(self, item: Customer, amount: int) -> int:
        """Take 5 percent off when the customer notes name more than 10 orders."""
        return amount * 95 // 100 if item.notes.count("order") > 10 else amount
'''},
    ("api/shopapi/services/{e}_service.py", "order"): {
        "IMPORTS": "from shopapi.services.customer_service import CustomerService\n",
        "EXTRA": '''
    def checkout_total(self, customers: CustomerService, item: Order) -> int:
        customer = customers.repo.load(item.notes)
        return customers.apply_loyalty_discount(customer, item.amount) if customer else item.amount
'''},
    ("api/shopapi/services/{e}_service.py", "payment"): {
        "IMPORTS": "from shopapi.models.refund import Refund\n",
        "EXTRA": '''
    def refund(self, item: Payment) -> Refund:
        return Refund(amount=item.amount, notes=f"refund of payment {item.id}")
'''},
    ("api/shopapi/services/{e}_service.py", "warehouse"): {"EXTRA": '''
    def reserve_stock(self, item_id: str, count: int) -> None:
        item = self.repo.load(item_id)
        item.amount -= count
        self.repo.save(item)

    def release_stock(self, item_id: str, count: int) -> None:
        item = self.repo.load(item_id)
        item.amount += count
        self.repo.save(item)

    def rebalance(self) -> int:
        return sum(1 for item in self.find_open() if item.amount < 0)
'''},
    ("web/src/api/{e}Api.ts", "invoice"): {"EXTRA": '''
export async function postSettlement(id: string): Promise<void> {
  await http.post(`/invoices/${id}/settlement`, {});
}
'''},
    ("web/src/stores/{e}Store.ts", "invoice"): {
        "IMPORTS": 'import { postSettlement } from "../api/invoiceApi";\n',
        "EXTRA": '''
  async settle(id: string): Promise<void> {
    await postSettlement(id);
    this.rows = this.rows.map((r) => (r.id === id ? { ...r, status: "closed" } : r));
  }
'''},
    ("web/src/stores/{e}Store.ts", "cart"): {
        "IMPORTS": 'import { fetchCoupon } from "../api/couponApi";\n',
        "EXTRA": '''
  async applyCoupon(cartId: string, couponId: string): Promise<void> {
    const coupon = await fetchCoupon(couponId);
    this.rows = this.rows.map((r) => (r.id === cartId ? { ...r, amount: r.amount - coupon.amount } : r));
  }
'''},
    ("tools/{e}/migrate.js", "supplier"): {"EXPORTS": ", rebuildSupplierCache", "EXTRA": '''
async function rebuildSupplierCache() {
  const db = await connect();
  await db.clear("supplier_cache");
  for (const row of await db.all("suppliers")) await db.insert("supplier_cache", row);
}
'''},
    ("tools/{e}/index.js", "supplier"): {"EXPORTS": ", rebuildSupplierCache",
                                         "CALLS": "\n    await rebuildSupplierCache();"},
    ("tools/{e}/report.js", "warehouse"): {
        "IMPORTS": 'const { rebuildSupplierCache } = require("../supplier/migrate");\n',
        "CALLS": "\n  await rebuildSupplierCache();"},
}


def rules(name: str, count: int = 24) -> str:
    """Functions that no chain calls. They make a whole-file read of an M3 file cost more (#279)."""
    return "".join(f'''
function {name}Rule{i:02d}(row) {{
  // Rule {i}: keep the row when field_{i} is set, else mark the row for review.
  if (row.field_{i} === undefined || row.field_{i} === null) {{
    return {{ ...row, review: [...(row.review || []), "field_{i}"] }};
  }}
  const value = String(row.field_{i}).trim();
  return {{ ...row, field_{i}: value.length > 64 ? value.slice(0, 64) : value }};
}}
''' for i in range(1, count + 1))


# The facts of the M scenarios. Some names repeat on purpose: NotificationService.record_event does
# not use the audit module, and fetchExchangeRates is not fetchExchangeRate.
AUDIT_IMPORT = "from shopapi.core.audit import record_event\n"
RATES_IMPORT = 'import { fetchExchangeRate } from "../lib/rates";\n'
MARKET_PLANTS = {
    ("api/shopapi/services/{e}_service.py", "shipment"): {"IMPORTS": AUDIT_IMPORT, "EXTRA": '''
    def ship(self, item_id: str) -> None:
        self.close(item_id)
        record_event("shipped", item_id)
'''},
    ("api/shopapi/services/{e}_service.py", "ledger"): {"IMPORTS": AUDIT_IMPORT, "EXTRA": '''
    def post_entry(self, item: object, amount: int) -> Ledger:
        entry = self.create(amount=amount, notes=f"entry for {item.id}")
        record_event("posted", entry.id)
        return entry
'''},
    ("api/shopapi/services/{e}_service.py", "subscription"): {"IMPORTS": AUDIT_IMPORT, "EXTRA": '''
    def renew(self, item_id: str, months: int = 1) -> None:
        item = self.repo.load(item_id)
        item.notes = f"renewed for {months} months"
        self.repo.save(item)
        record_event("renewed", item_id)
'''},
    ("api/shopapi/handlers/{e}_handler.py", "account"): {"IMPORTS": "from shopapi.core.audit import audit_path\n",
                                                         "EXTRA": '''

def handle_audit_file(service: AccountService, request: Request) -> Response:
    return Response(200, {"path": audit_path(request.tenant)})
'''},
    ("api/shopapi/services/{e}_service.py", "notification"): {"EXTRA": '''
    def record_event(self, kind: str, item_id: str) -> None:
        self.create(notes=f"{kind}: {item_id}")
'''},
    ("api/shopapi/services/{e}_service.py", "payout"): {
        "IMPORTS": "from shopapi.core.fx import convert_amount\n"
                   "from shopapi.services.ledger_service import LedgerService\n",
        "EXTRA": '''
    def settle_batch(self, ledger: LedgerService, currency: str) -> int:
        """Post each open payout to the ledger in the currency, then close it."""
        count = 0
        for item in self.find_open():
            ledger.post_entry(item, convert_amount(item.amount, currency))
            self.close(item.id)
            count += 1
        return count
'''},
    ("web/src/stores/{e}Store.ts", "ledger"): {"IMPORTS": RATES_IMPORT, "EXTRA": '''
  async convert(id: string, currency: string): Promise<number> {
    const rate = await fetchExchangeRate(currency);
    return Math.round((this.rows.find((r) => r.id === id)?.amount ?? 0) * rate);
  }
'''},
    ("web/src/stores/{e}Store.ts", "payout"): {"IMPORTS": RATES_IMPORT, "EXTRA": '''
  async preview(id: string): Promise<string> {
    const rate = await fetchExchangeRate("EUR");
    return `${id}: ${rate}`;
  }
'''},
    ("web/src/api/{e}Api.ts", "quote"): {"EXTRA": '''
export async function priceQuote(id: string, currency: string): Promise<number> {
  const { fetchExchangeRate } = await import("../lib/rates");
  const row = await fetchQuote(id);
  return row.amount * (await fetchExchangeRate(currency));
}
'''},
    ("web/src/api/{e}Api.ts", "rate"): {"EXTRA": '''
export async function fetchExchangeRates(): Promise<Record<string, number>> {
  return http.get("/rates");
}
'''},
    ("tools/{e}/index.js", "vendor"): {"EXPORTS": ", syncVendors",
                                       "COMMANDS": '  if (command === "sync") return syncVendors(argv[3]);\n'},
    ("tools/{e}/migrate.js", "vendor"): {
        "IMPORTS": 'const { normalizeVendor } = require("../lib/normalize");\n'
                   'const { pushToLedger } = require("../ledger/migrate");\n',
        "EXPORTS": ", syncVendors", "EXTRA": rules("checkVendor") + '''
async function syncVendors(source) {
  const db = await connect();
  const rows = await db.all(source || "vendor_feed");
  for (const row of rows) await pushToLedger(normalizeVendor(row));
  log(`synced ${rows.length} vendors`);
}
'''},
    ("tools/{e}/migrate.js", "ledger"): {"EXPORTS": ", pushToLedger", "EXTRA": rules("checkEntry") + '''
async function pushToLedger(entry) {
  const db = await connect();
  await db.insert("ledger_entries", entry);
}
'''},
}

MARKET_SHARED = {
    "api/shopapi/core/audit.py": '''from pathlib import Path

EVENTS: list[tuple[str, str]] = []


def record_event(kind: str, item_id: str) -> None:
    EVENTS.append((kind, item_id))


def audit_path(tenant: str) -> Path:
    return Path("audit") / f"{tenant}.log"
''',
    "api/shopapi/core/fx.py": '''RATES = {"USD": 1.0, "EUR": 0.9}


def convert_amount(amount: int, currency: str) -> int:
    return round(amount * RATES[currency])
''',
    "web/src/lib/rates.ts": '''import { http } from "./http";

export async function fetchExchangeRate(currency: string): Promise<number> {
  return http.get(`/rates/${currency}`);
}
''',
    "tools/lib/normalize.js": rules("cleanVendor").lstrip() + '''
function normalizeVendor(row) {
  return { id: `vendor-${row.id}`, amount: Number(row.amount) || 0, status: "new" };
}

module.exports = { normalizeVendor };
''',
    "tools/lib/memory-db.js": '''const tables = new Map();

function table(name) {
  if (!tables.has(name)) tables.set(name, new Map());
  return tables.get(name);
}

function open() {
  return {
    all: async (name) => [...table(name).values()],
    insert: async (name, row) => { table(name).set(row.id, row); },
    update: async (name, id, fields) => { table(name).set(id, { ...table(name).get(id), ...fields }); },
    clear: async (name) => { table(name).clear(); },
  };
}

module.exports = { open };
''',
    # A file with "sync" in its name that the sync command does not run. M3 fails an answer that names it.
    "tools/vendor/sync.js": '''const { connect } = require("../lib/db");

async function syncVendorFeed(rows) {
  const db = await connect();
  for (const row of rows) await db.insert("vendors", row);
}

module.exports = { syncVendorFeed };
''',
}

SHARED = {
    "README.md": "# Shop\n\nThe shop API (`api/`), the web app (`web/`), and the data tools (`tools/`).\n",
    "api/pyproject.toml": '[project]\nname = "shopapi"\nversion = "0.1.0"\n',
    "web/package.json": '{"name": "shop-web", "private": true}\n',
    "tools/package.json": '{"name": "shop-tools", "private": true}\n',
    **{f"api/shopapi/{part}__init__.py": "" for part in
       ("", "core/", "models/", "repo/", "services/", "handlers/")},
    "api/shopapi/core/ids.py": "import uuid\n\n\ndef new_id() -> str:\n    return uuid.uuid4().hex\n",
    "api/shopapi/core/db.py": '''class Database:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict]] = {}

    def fetch_one(self, table: str, key: str) -> dict | None:
        return self.tables.get(table, {}).get(key)

    def fetch_all(self, table: str) -> list[dict]:
        return list(self.tables.get(table, {}).values())

    def upsert(self, table: str, row: dict) -> None:
        self.tables.setdefault(table, {})[row["id"]] = row

    def delete(self, table: str, key: str) -> None:
        self.tables.get(table, {}).pop(key, None)
''',
    "api/shopapi/core/http.py": '''from dataclasses import dataclass, field


@dataclass
class Request:
    params: dict = field(default_factory=dict)
    body: dict = field(default_factory=dict)
    tenant: str = ""


@dataclass
class Response:
    status: int
    body: dict
''',
    "api/shopapi/core/limits.py": '''from shopapi.core.http import Request

LIMITS = {"free": 100, "team": 10_000}


def check_quota(request: Request, used: int, plan: str = "free") -> None:
    if used >= LIMITS[plan]:
        raise PermissionError(f"quota exceeded for tenant {request.tenant}")
''',
    "web/src/lib/http.ts": '''export const http = {
  async get(path: string) {
    return (await fetch(path)).json();
  },
  async post(path: string, body: unknown) {
    await fetch(path, { method: "POST", body: JSON.stringify(body) });
  },
};
''',
    "web/src/lib/format.ts": '''export function formatMoney(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}
''',
    "tools/lib/log.js": "function log(text) {\n  console.log(`[tools] ${text}`);\n}\n\nmodule.exports = { log };\n",
    "tools/lib/db.js": "async function connect() {\n  return require(\"./memory-db\").open();\n}\n\n"
                       "module.exports = { connect };\n",
}


def fill(template: str, entity: str, slots: dict[str, str]) -> str:
    text = template
    for name in ("IMPORTS", "EXTRA", "EXPORTS", "CALLS", "COMMANDS"):
        text = text.replace("{" + name + "}", slots.get(name, ""))
    return (text.replace("{E}", entity.capitalize()).replace("{U}", entity.upper())
            .replace("{e}", entity))


def make(out: Path, entities: tuple[str, ...] = ENTITIES, shared: dict[str, str] | None = None,
         plants: dict[tuple[str, str], dict[str, str]] | None = None) -> int:
    shutil.rmtree(out, ignore_errors=True)
    files = dict(SHARED if shared is None else shared)
    plants = PLANTS if plants is None else plants
    for entity in entities:
        for path, template in {**PY, **TS, **JS}.items():
            files[fill(path, entity, {})] = fill(template, entity, plants.get((path, entity), {}))
    for path, text in sorted(files.items()):
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_text(text, encoding="utf-8")
    return len(files)


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "fixtures"
    print(f"wrote {make(folder / 'shop')} files to {folder / 'shop'}")
    count = make(folder / "market", MARKET_ENTITIES, {**SHARED, **MARKET_SHARED}, {**PLANTS, **MARKET_PLANTS})
    print(f"wrote {count} files to {folder / 'market'}")
