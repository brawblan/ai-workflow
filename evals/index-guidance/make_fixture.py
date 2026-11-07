"""Make the fixture of the guidance.index eval (D107): a shop repo of 228 files.

Usage: python3 make_fixture.py [<output folder>]. The default is `fixtures/shop` next to this file.
The script deletes the folder first, and the output is the same on each run. 14 entities get 5
Python, 5 TypeScript, and 5 JavaScript files each. They share a few common names (`load`, `save`,
`Store`), as in a real repo. PLANTS has the facts that the scenarios ask about.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ENTITIES = ("order", "invoice", "customer", "product", "shipment", "payment", "refund", "coupon",
            "warehouse", "supplier", "review", "cart", "wishlist", "notification")

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
''',
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
  throw new Error(`unknown command: ${command}`);
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
    for name in ("IMPORTS", "EXTRA", "EXPORTS", "CALLS"):
        text = text.replace("{" + name + "}", slots.get(name, ""))
    return (text.replace("{E}", entity.capitalize()).replace("{U}", entity.upper())
            .replace("{e}", entity))


def make(out: Path) -> int:
    shutil.rmtree(out, ignore_errors=True)
    files = dict(SHARED)
    for entity in ENTITIES:
        for path, template in {**PY, **TS, **JS}.items():
            files[fill(path, entity, {})] = fill(template, entity, PLANTS.get((path, entity), {}))
    for path, text in sorted(files.items()):
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_text(text, encoding="utf-8")
    return len(files)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "fixtures/shop"
    print(f"wrote {make(target)} files to {target}")
