import json
import boto3
import time
import random
import string

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
sns_client = boto3.client('sns', region_name='us-east-1')

visitors_table = dynamodb.Table('visitors')
passcodes_table = dynamodb.Table('passcodes')

OWNER_PHONE = "+13134138327"
WP2_URL = "http://smartdoor-web-yk-2025.s3-website-us-east-1.amazonaws.com/wp2.html"

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def lambda_handler(event, context):
    print(f"📥 Event received: {json.dumps(event)}")
    
    try:
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
        else:
            body = event
        
        face_id = body.get('faceId', f'unknown-{int(time.time())}')
        name = body.get('name')
        phone = body.get('phoneNumber')
        
        print(f"📋 Parsed input: Name: {name}, Phone: {phone}, FaceID: {face_id}")
        
        if not name or not phone:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'status': 'error', 'message': 'Name and phone required'})
            }
        
        phone_normalized = (phone if phone.startswith('+') else f"+1{phone}").replace(' ', '')
        print(f"📱 Normalized phone: {phone_normalized}")
        
        # Add visitor
        visitors_table.put_item(Item={
            'faceId': face_id,
            'name': name,
            'phoneNumber': phone_normalized,
            'photos': [],
            'createdAt': int(time.time())
        })
        print(f"✅ Visitor added: {name}")
        
        # Generate OTP
        otp = generate_otp()
        print(f"🔐 OTP generated: {otp}")
        
        # Store OTP with OTP as PARTITION KEY
        expiry_time = int(time.time()) + (24 * 3600)
        passcodes_table.put_item(Item={
            'otp': otp,  # ← PARTITION KEY
            'phone': phone_normalized,
            'name': name,
            'faceId': face_id,
            'createdAt': int(time.time()),
            'expiresAt': expiry_time
        })
        print(f"✅ OTP stored in DynamoDB")
        
        # Send SMS
        try:
            message = f"Your Smart Door OTP is: {otp}\n\nEnter it here: {WP2_URL}\n\nValid for 24 hours."
            sns_response = sns_client.publish(
                PhoneNumber=phone_normalized,
                Message=message,
                MessageAttributes={
                    'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'}
                }
            )
            print(f"✅ SMS sent to {phone_normalized}")
        except Exception as sms_error:
            print(f"❌ SMS failed: {str(sms_error)}")
            raise
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({
                'status': 'ok',
                'message': f'OTP sent to {phone_normalized}',
                'faceId': face_id
            })
        }
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
