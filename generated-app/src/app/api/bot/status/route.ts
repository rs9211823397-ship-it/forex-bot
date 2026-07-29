import { NextResponse } from "next/server";
import { getBotState } from "@/lib/bot/controller";

export const dynamic = "force-dynamic";

// Shared by web dashboard AND mobile apps (same API, Bearer or cookie auth)
export async function GET() {
  const state = await getBotState();
  return NextResponse.json({ bot: state });
}
