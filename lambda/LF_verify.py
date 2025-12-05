import json
import time
import boto3

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

# DynamoDB tables
PASSCODES_TABLE_NAME = 'passcodes'
VISITORS_TABLE_NAME = 'visitors'

passcodes_table = dynamodb.Table(PASSCODES_TABLE_NAME)
visitors_table = dynamodb.Table(VISITORS_TABLE_NAME)


def response(status_code, success, message, data=None):
    """Standard HTTP response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        },
        "body": json.dumps({
            "success": success,
            "status": "ok" if success else "error",
            "message": message,
            "data": data or {}
        })
    }


def lambda_handler(event, context):
    print("=" * 80)
    print("📥 LF_verify Lambda started")
    print("Event:", json.dumps(event))

    # Parse body
    try:
        if "body" in event:
            body = event["body"]
            if isinstance(body, str):
                body = json.loads(body)
        else:
            body = event
    except Exception as e:
        print("❌ Body parse error:", str(e))
        return response(400, False, "Invalid request body")

    otp = (body.get("otp") or "").strip()
    phone = (body.get("phone") or "").strip()
    face_id_from_client = (body.get("faceId") or "").strip()

    print(f"🔑 OTP: {otp}")
    print(f"📱 Phone: {phone}")
    print(f"📷 FaceId (from client): {face_id_from_client}")

    if not otp or not phone:
        return response(400, False, "Missing otp or phone")

    now = int(time.time())

    # 1️⃣ Look up OTP in passcodes table
    try:
        print("🔍 Looking up OTP in passcodes table...")
        otp_item_resp = passcodes_table.get_item(Key={"otp": otp})
        otp_item = otp_item_resp.get("Item")
    except Exception as e:
        print("❌ DynamoDB error (passcodes):", str(e))
        return response(500, False, "Database error while checking OTP")

    if not otp_item:
        print("❌ No OTP item found")
        return response(
            400,
            False,
            "Invalid OTP",
            {"errorCode": "OTP_INVALID"}
        )

    stored_phone = otp_item.get("visitorPhone") or otp_item.get("phone")
    expires_at = int(otp_item.get("expiresAt", 0))
    passcode_status = (otp_item.get("status") or "approved").lower()
    face_id = otp_item.get("faceId") or face_id_from_client
    visitor_name = otp_item.get("visitorName") or otp_item.get("name") or "Guest"

    print(f"✅ OTP item: status={passcode_status}, phone={stored_phone}, expiresAt={expires_at}, faceId={face_id}")

    # 2️⃣ Check phone matches (if stored)
    if stored_phone and stored_phone != phone:
        print("❌ Phone does not match OTP record")
        return response(
            400,
            False,
            "This OTP does not match your phone number",
            {"errorCode": "PHONE_MISMATCH"}
        )

    # 3️⃣ Check expiry
    if expires_at and expires_at < now:
        print("❌ OTP expired")
        return response(
            400,
            False,
            "OTP has expired. Please request a new one.",
            {"errorCode": "OTP_EXPIRED"}
        )

    # 4️⃣ If owner REJECTED the visit (passcodes)
    if passcode_status == "rejected":
        print("🚫 Visit was rejected by the owner (passcodes table)")
        return response(
            403,
            False,
            "Your visit request was rejected by the owner.",
            {
                "errorCode": "VISIT_REJECTED",
                "status": "rejected",
                "visitorName": visitor_name,
                "faceId": face_id
            }
        )

    # 5️⃣ Optional: also check visitors table (extra safety)
    visitor_status = "approved"
    try:
        if face_id:
            print("🔍 Loading visitor from visitors table...")
            visitor_resp = visitors_table.get_item(Key={"faceId": face_id})
            visitor = visitor_resp.get("Item")
            if visitor:
                visitor_name = visitor.get("visitorName") or visitor.get("name") or visitor_name
                visitor_status = (visitor.get("status") or "approved").lower()
                print(f"✅ Visitor status = {visitor_status}")

    except Exception as e:
        print("⚠️ Could not load visitor from visitors table:", str(e))

    # If visitors table says REJECTED, also block
    if visitor_status == "rejected":
        print("🚫 Visit was rejected by the owner (visitors table)")
        return response(
            403,
            False,
            "Your visit request was rejected by the owner.",
            {
                "errorCode": "VISIT_REJECTED",
                "status": "rejected",
                "visitorName": visitor_name,
                "faceId": face_id
            }
        )

    # 6️⃣ Mark OTP as used (so it can't be reused)
    try:
        passcodes_table.update_item(
            Key={"otp": otp},
            UpdateExpression="SET #status = :used, usedAt = :now",
            ExpressionAttributeNames={
                "#status": "status"
            },
            ExpressionAttributeValues={
                ":used": "used",
                ":now": now
            }
        )
        print("🔐 Marked OTP as used")
    except Exception as e:
        print("⚠️ Failed to mark OTP as used:", str(e))

    print("✅ OTP verified and access granted")

    return response(
        200,
        True,
        "OTP verified successfully. Access granted.",
        {
            "status": "approved",
            "visitorName": visitor_name,
            "faceId": face_id
        }
    )