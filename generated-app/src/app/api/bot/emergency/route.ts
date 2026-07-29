import { NextResponse } from "next/server";
import { commandBot } from "@/lib/bot/controller";
import { requireUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

// EMERGENCY STOP (Feature 1) — requires explicit user confirmation;
// optionally closes all open positions when `closePositions: true`
export async function POST(req: Request) {
  const auth = await requireUser(req);
  const body = (await req.json().catch(() => ({}))) as { confirm?: boolean; closePositions?: boolean };
  if (body.confirm !== true) {
    return NextResponse.json(
      { error: "Emergency stop requires explicit confirmation: { confirm: true, closePositions?: boolean }" },
      { status: 400 },
    );
  }
  const result = await commandBot("emergency", {
    closeOpenPositions: body.closePositions === true,
    updatedBy: auth.username,
  });
  return NextResponse.json({ ok: result.ok, state: result, closedPositions: result.closedPositions ?? 0 });
}
