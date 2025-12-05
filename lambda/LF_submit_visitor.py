import json
import boto3
import time
import random
import string
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
s3_client = boto3.client('s3', region_name='us-east-1')
sns = boto3.client('sns', region_name='us-east-1')
ses = boto3.client('ses', region_name='us-east-1')

visitors_table = dynamodb.Table('visitors')
passcodes_table = dynamodb.Table('passcodes')

BUCKET_NAME = 'smartdoor-visitor-photos-yk-2025'
PHOTO_PREFIX = 'test-faces'
OWNER_EMAIL = 'yatinrags135@gmail.com'


def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


def response(status_code, success, message, data=None):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'success': success,
            'message': message,
            'data': data or {}
        })
    }


def lambda_handler(event, context):
    """Handle visitor form submission"""

    print("=" * 80)
    print("📥 LF_submit_visitor Lambda Started")
    print("=" * 80)

    try:
        # Parse request
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
        else:
            body = event

        face_id = body.get('faceId')
        photo_base64 = body.get('photo')
        visitor_name = body.get('visitorName', '').strip()
        visitor_phone = body.get('visitorPhone', '').strip()
        visitor_email = body.get('visitorEmail', '').strip()
        visit_reason = body.get('visitReason', '').strip()

        print(f"👤 Name: {visitor_name}")
        print(f"📱 Phone: {visitor_phone}")
        print(f"📧 Email: {visitor_email}")
        print(f"📍 FaceId: {face_id}")

        # Validate
        if not face_id or not photo_base64 or not visitor_name or not visitor_phone:
            return response(400, False, 'Missing required fields')

        current_time = int(time.time())

        # 0️⃣ Check if this user already has an active visit
        #    (same phone, status pending/approved, not yet expired)
        try:
            print("\n[0️⃣] Checking for existing active visit for this phone...")
            scan_resp = visitors_table.scan(
                FilterExpression=(
                    Attr('visitorPhone').eq(visitor_phone) &
                    Attr('status').is_in(['pending', 'approved']) &
                    Attr('expiresAt').gt(current_time)
                )
            )
            existing_items = scan_resp.get('Items', [])
            if existing_items:
                existing = existing_items[0]
                print("🚫 Existing active visit found:", existing.get('faceId'))
                return response(
                    409,
                    False,
                    "You are already registered as an existing visitor.",
                    {
                        "errorCode": "VISITOR_EXISTS",
                        "faceId": existing.get('faceId'),
                        "visitorName": existing.get('visitorName') or existing.get('name')
                    }
                )
        except Exception as e:
            print(f"⚠️ Error checking existing visitor: {str(e)}")
            # Not fatal; we continue with submission

        # ===== 1️⃣ UPLOAD PHOTO TO S3 =====
        print("\n[1️⃣] Uploading photo to S3...")

        try:
            if ',' in photo_base64:
                photo_bytes = __import__('base64').b64decode(photo_base64.split(',')[1])
            else:
                photo_bytes = __import__('base64').b64decode(photo_base64)

            s3_key = f'{PHOTO_PREFIX}/{face_id}.jpg'

            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=s3_key,
                Body=photo_bytes,
                ContentType='image/jpeg'
            )

            # Generate public URL
            photo_url = f'https://{BUCKET_NAME}.s3.us-east-1.amazonaws.com/{s3_key}'
            print(f"✅ Photo uploaded: {photo_url}")

        except Exception as e:
            print(f"❌ S3 error: {str(e)}")
            return response(500, False, f'Photo upload error: {str(e)}')

        # ===== 2️⃣ GENERATE OTP & SAVE TO DYNAMODB =====
        print("\n[2️⃣] Generating OTP and saving to DynamoDB...")

        try:
            otp = generate_otp()
            otp_expires = current_time + 600  # 10 minutes

            print(f"🔐 Generated OTP: {otp}")

            # Save to visitors table
            visitors_table.put_item(Item={
                'faceId': face_id,
                'visitorName': visitor_name,
                'visitorPhone': visitor_phone,
                'visitorEmail': visitor_email,
                'visitReason': visit_reason,
                'photoUrl': photo_url,
                'status': 'pending',
                'otp': otp,
                'createdAt': current_time,
                'expiresAt': otp_expires
            })

            print(f"✅ Visitor saved to visitors table")

            # Save to passcodes table (for OTP verification)
            print(f"💾 Saving to passcodes table...")
            passcodes_table.put_item(
                Item={
                    'otp': otp,
                    'phone': visitor_phone,
                    'name': visitor_name,
                    'faceId': face_id,
                    'expiresAt': otp_expires,
                    'createdAt': current_time,
                    'status': 'pending'   # will be updated to approved/rejected later
                }
            )
            print(f"✅ OTP saved to passcodes table")

        except Exception as e:
            print(f"❌ Database error: {str(e)}")
            return response(500, False, f'Database error: {str(e)}')

        # ===== 3️⃣ SEND OTP VIA SMS TO VISITOR =====
        print("\n[3️⃣] Sending OTP via SMS to visitor...")

        try:
            sms_message = (
                f"Your Smart Door verification code is: {otp}\n\n"
                f"Valid for 10 minutes.\nDo not share this code."
            )

            print(f"📱 Sending SMS to {visitor_phone}...")

            sns_response = sns.publish(
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

            print(f"✅ SMS sent successfully!")
            print(f"   MessageId: {sns_response['MessageId']}")

        except Exception as sms_error:
            print(f"⚠️ SMS sending warning: {str(sms_error)}")
            print(f"   OTP is saved in database for manual lookup in CloudWatch")

        # ===== 4️⃣ SEND EMAIL TO OWNER WITH VISITOR DETAILS =====
        print("\n[4️⃣] Sending email to owner with visitor details...")

        try:
            email_body = f'''
            <html>
            <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                    <h2 style="color: #333; text-align: center;">🚪 New Visitor Awaiting Approval</h2>

                    <p style="color: #666;"><strong>Visitor Details:</strong></p>
                    <ul style="color: #666; line-height: 1.8;">
                        <li><strong>Name:</strong> {visitor_name}</li>
                        <li><strong>Phone:</strong> {visitor_phone}</li>
                        <li><strong>Email:</strong> {visitor_email or 'Not provided'}</li>
                        <li><strong>Visit Reason:</strong> {visit_reason or 'Not specified'}</li>
                        <li><strong>Face ID:</strong> {face_id}</li>
                    </ul>

                    <p style="color: #666;"><strong>📸 Visitor Photo:</strong></p>
                    <img src="{photo_url}" width="300" style="border-radius: 8px; border: 1px solid #ddd; margin: 15px 0;">

                    <p style="color: #666;"><strong>🔐 OTP Code to Share with Visitor:</strong></p>
                    <div style="background: #f0f9ff; border: 2px solid #0284c7; border-radius: 8px; padding: 20px; text-align: center; margin: 20px 0;">
                        <p style="font-size: 24px; font-weight: bold; letter-spacing: 3px; color: #0284c7; margin: 0;">{otp}</p>
                    </div>

                    <p style="text-align: center; margin: 20px 0;">
                        <a href="https://smartdoor-web-yk-2025.s3.us-east-1.amazonaws.com/wp1.html" 
                           style="background-color: #10b981; color: white; padding: 12px 24px; 
                                  text-decoration: none; border-radius: 8px; display: inline-block; font-weight: bold;">
                            👉 Review & Approve in Dashboard
                        </a>
                    </p>

                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    <p style="color: #999; font-size: 12px; text-align: center;">
                        Smart Door System | {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                    </p>
                </div>
            </body>
            </html>
            '''

            print(f"📧 Sending email to {OWNER_EMAIL}...")

            ses.send_email(
                Source=OWNER_EMAIL,
                Destination={'ToAddresses': [OWNER_EMAIL]},
                Message={
                    'Subject': {'Data': f'🚪 New Visitor: {visitor_name} - Awaiting Approval'},
                    'Body': {'Html': {'Data': email_body}}
                }
            )

            print(f"✅ Email sent to owner!")

        except Exception as email_error:
            print(f"⚠️ Email sending warning: {str(email_error)}")
            print(f"   Visitor info is still saved in database")

        # ===== 5️⃣ LOG TO CLOUDWATCH =====
        print("\n" + "=" * 80)
        print("🔐 OTP DETAILS - VISIBLE IN CLOUDWATCH LOGS")
        print("=" * 80)
        print(f"OTP:         {otp}")
        print(f"Phone:       {visitor_phone}")
        print(f"Name:        {visitor_name}")
        print(f"FaceID:      {face_id}")
        print(f"ExpiresAt:   {otp_expires}")
        print(f"SMS Status:  Sent to {visitor_phone}")
        print(f"Email Status: Sent to {OWNER_EMAIL}")
        print("=" * 80 + "\n")

        print("[✅] Submission Complete!")
        print("=" * 80)

        return response(200, True, 'Visitor details submitted! OTP sent via SMS, email sent to owner.', {
            'faceId': face_id,
            'otp': otp,
            'photoUrl': photo_url,
            'visitorName': visitor_name,
            'visitorPhone': visitor_phone
        })

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return response(500, False, f'Error: {str(e)}')