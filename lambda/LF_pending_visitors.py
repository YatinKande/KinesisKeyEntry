import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3

dynamodb = boto3.resource("dynamodb")
VISITORS_TABLE_NAME = os.environ.get("VISITORS_TABLE_NAME", "visitors")

S3_BUCKET = os.environ.get("VISITOR_PHOTO_BUCKET", "smartdoor-visitor-photos-yk-2025")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

visitors_table = dynamodb.Table(VISITORS_TABLE_NAME)


def decimal_to_int(value):
    if isinstance(value, Decimal):
        return int(value)
    return value


def build_response(status_code, body_dict):
    """HTTP response with CORS so wp1.html can call it from S3/localhost."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body_dict),
    }


def lambda_handler(event, context):
    print("=" * 80)
    print("📥 LF_pending_visitors called")
    print("Event:", json.dumps(event))

    try:
        # 1) Read ALL visitors from DynamoDB
        scan_kwargs = {}
        all_items = []

        while True:
            resp = visitors_table.scan(**scan_kwargs)
            all_items.extend(resp.get("Items", []))

            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key

        print(f"🔍 Total visitors loaded from DynamoDB: {len(all_items)}")

        now = int(time.time())
        visitors_out = []

        for item in all_items:
            # --- Basic fields from Dynamo ---
            face_id = item.get("faceId")
            # Support both old and new attribute names
            visitor_name = item.get("visitorName") or item.get("name")
            visitor_phone = item.get("visitorPhone") or item.get("phoneNumber")
            visitor_email = item.get("visitorEmail") or item.get("email")
            visit_reason = item.get("visitReason")

            otp = item.get("otp")

            created_at = decimal_to_int(item.get("createdAt", 0))
            approved_at = decimal_to_int(item.get("approvedAt", 0))
            rejected_at = decimal_to_int(item.get("rejectedAt", 0))
            expires_at = decimal_to_int(item.get("expiresAt", 0))
            updated_at = decimal_to_int(item.get("updatedAt", 0))

            # --- Derive STATUS for UI ---
            status = item.get("status")
            if not status:
                if approved_at:
                    status = "approved"
                elif rejected_at:
                    status = "rejected"
                else:
                    # still pending unless expired
                    if expires_at and expires_at < now:
                        status = "expired"
                    else:
                        status = "pending"

            # --- PHOTO URL for card view ---
            # 1) Prefer the direct photoUrl field created by LF_submit_visitor
            photo_url = item.get("photoUrl")

            # 2) Fallback: build from S3 key if only the key is stored
            if not photo_url:
                photo_key = item.get("photoS3Key") or item.get("photoKey")
                if photo_key:
                    photo_url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{photo_key}"

            # --- Human friendly createdAt for UI ---
            created_formatted = None
            if created_at:
                created_formatted = datetime.fromtimestamp(
                    created_at, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC")

            visitors_out.append(
                {
                    "faceId": face_id,
                    "visitorName": visitor_name,
                    "visitorPhone": visitor_phone,
                    "visitorEmail": visitor_email,
                    "visitReason": visit_reason,
                    "status": status,
                    "otp": otp,
                    "photoUrl": photo_url,  # 👈 now always filled when possible
                    "createdAt": created_at,
                    "createdAtFormatted": created_formatted,
                    "approvedAt": approved_at,
                    "rejectedAt": rejected_at,
                    "updatedAt": updated_at,
                    "expiresAt": expires_at,
                }
            )

        print(f"✅ Returning {len(visitors_out)} visitors to dashboard")

        return build_response(
            200,
            {
                "success": True,
                "message": "OK",
                "data": {"visitors": visitors_out},
            },
        )

    except Exception as e:
        print("❌ Error in LF_pending_visitors:", str(e))
        return build_response(
            500,
            {"success": False, "message": f"Error loading visitors: {str(e)}"},
        )