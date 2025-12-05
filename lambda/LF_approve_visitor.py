import json
import boto3
import time
import random
import string
from decimal import Decimal

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
sns_client = boto3.client('sns', region_name='us-east-1')

visitors_table = dynamodb.Table('visitors')
passcodes_table = dynamodb.Table('passcodes')

WP2_URL = "https://smartdoor-web-yk-2025.s3.us-east-1.amazonaws.com/wp2.html"
SNS_TOPIC_ARN = 'arn:aws:sns:us-east-1:317587885753:smartdoor-notifications'


def response(status_code, success, message, data=None):
    """Build HTTP response with proper CORS headers"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        },
        'body': json.dumps({
            'success': success,
            'status': 'ok' if success else 'error',
            'message': message,
            'data': data or {}
        })
    }


def lambda_handler(event, context):
    """
    Handle both APPROVE and REJECT actions from owner dashboard.
    Also updates the OTP record in passcodes table so that
    rejected visitors cannot use their OTP anymore.
    """

    print("=" * 80)
    print("📥 LF_approve_visitor Lambda Started")
    print(json.dumps(event))
    print("=" * 80)

    try:
        # Parse request body
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
        else:
            body = event

        face_id = body.get('faceId', '').strip()
        action = body.get('action', '').strip()  # "approve" or "reject"

        print(f"📍 FaceID: {face_id}")
        print(f"🔄 Action: {action}")

        # Validate inputs
        if not face_id or not action:
            return response(400, False, 'Missing faceId or action')

        if action not in ['approve', 'reject']:
            return response(400, False, 'Action must be "approve" or "reject"')

        # 1️⃣ Get visitor from visitors table
        print("\n[1️⃣] Getting visitor from database...")

        try:
            visitor_obj = visitors_table.get_item(Key={'faceId': face_id})
            visitor = visitor_obj.get('Item')

            if not visitor:
                return response(404, False, 'Visitor not found')

            visitor_name = visitor.get('visitorName', visitor.get('name', 'Visitor'))
            visitor_phone = visitor.get('visitorPhone', visitor.get('phoneNumber'))
            otp = visitor.get('otp')

            print(f"✅ Found visitor: {visitor_name}")
            print(f"   Phone: {visitor_phone}")
            print(f"   OTP:   {otp}")

        except Exception as e:
            print(f"❌ Database error (visitors): {str(e)}")
            return response(500, False, f'Database error: {str(e)}')

        # 2️⃣ Update visitor status
        print(f"\n[2️⃣] Updating visitor status to '{action}'...")

        try:
            current_time = int(time.time())

            if action == 'approve':
                new_status = 'approved'
                update_expr = 'SET #status = :status, updatedAt = :updated_at, approvedAt = :approved_at'
                expr_values = {
                    ':status': new_status,
                    ':updated_at': current_time,
                    ':approved_at': current_time
                }
            else:
                new_status = 'rejected'
                update_expr = 'SET #status = :status, updatedAt = :updated_at'
                expr_values = {
                    ':status': new_status,
                    ':updated_at': current_time
                }

            visitors_table.update_item(
                Key={'faceId': face_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames={
                    '#status': 'status'
                },
                ExpressionAttributeValues=expr_values
            )

            print(f"✅ Visitor status updated to '{new_status}'")

        except Exception as e:
            print(f"❌ Update error (visitors): {str(e)}")
            return response(500, False, f'Update error: {str(e)}')

        # 3️⃣ Update related OTP in passcodes table
        if otp:
            print("\n[3️⃣] Updating passcodes table with new status...")

            try:
                passcodes_table.update_item(
                    Key={'otp': otp},
                    UpdateExpression='SET #status = :status, updatedAt = :updated_at',
                    ExpressionAttributeNames={
                        '#status': 'status'
                    },
                    ExpressionAttributeValues={
                        ':status': new_status,
                        ':updated_at': current_time
                    }
                )
                print(f"✅ Passcode status set to '{new_status}' for otp={otp}")
            except Exception as e:
                print(f"⚠️ Could not update passcodes table: {str(e)}")
        else:
            print("⚠️ No OTP on visitor item; skipping passcodes update")

        # 4️⃣ Send SMS notification to visitor
        print(f"\n[4️⃣] Sending SMS notification to visitor...")

        try:
            if action == 'approve':
                sms_message = (
                    f"✅ Your visit has been APPROVED!\n\n"
                    f"Your OTP is: {otp}\n\n"
                    f"Enter it at: {WP2_URL}\n\n"
                    f"Valid for 10 minutes."
                )
            else:
                sms_message = (
                    "❌ Your visit request has been REJECTED.\n\n"
                    "Please contact the owner for more information."
                )

            print(f"📱 Sending SMS to {visitor_phone}...")
            sns_response = sns_client.publish(
                PhoneNumber=visitor_phone,
                Message=sms_message,
                MessageAttributes={
                    'AWS.SNS.SMS.SenderID': {
                        'DataType': 'String',
                        'StringValue': 'SmartDoor'
                    },
                    'AWS.SNS.SMS.SMSType': {
                        'DataType': 'String',
                        'StringValue': 'Transactional'
                    }
                }
            )

            print(f"✅ SMS sent! MessageId: {sns_response.get('MessageId')}")

        except Exception as sms_error:
            print(f"⚠️ SMS warning: {str(sms_error)}")

        # 5️⃣ Final response
        print("\n" + "=" * 80)
        print(f"✅ Visitor {action}ed successfully!")
        print("=" * 80)

        return response(200, True, f'Visitor {action}ed successfully! SMS sent to visitor.', {
            'faceId': face_id,
            'visitorName': visitor_name,
            'action': action,
            'newStatus': new_status,
            'smsSent': True
        })

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return response(500, False, f'Error: {str(e)}')