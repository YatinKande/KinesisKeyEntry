import json
import boto3
import base64
import time
import random
from datetime import datetime
from urllib.parse import urlencode

kinesis_client = boto3.client('kinesis', region_name='us-east-1')
s3_client = boto3.client('s3', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
ses_client = boto3.client('ses', region_name='us-east-1')
sns_client = boto3.client('sns', region_name='us-east-1')

# ===== CONFIGURATION =====
KINESIS_STREAM = 'smartdoor-kds'
S3_BUCKET = 'smartdoor-visitor-photos-yk-2025'
DYNAMODB_TABLE = 'Visitors'
OWNER_EMAIL = 'yatinrags135@gmail.com'
OWNER_PHONE = '+13134138327'
SNS_TOPIC_ARN = 'arn:aws:sns:us-east-1:317587885753:smartdoor-notifications'
WEB_BASE_URL = 'https://smartdoor-web-yk-2025.s3.us-east-1.amazonaws.com'

def lambda_handler(event, context):
    """Process Kinesis records for visitor detection."""
    print(f"📥 Processing {len(event['Records'])} records")
    
    try:
        for record in event['Records']:
            payload = json.loads(base64.b64decode(record['kinesis']['data']))
            
            face_id = payload.get('faceId')
            photo_s3_key = payload.get('photoS3Key')
            
            print(f"📷 Processing: {face_id}")
            
            # Check if visitor exists
            visitor = check_visitor_in_dynamodb(face_id)
            
            if visitor and visitor.get('status') == 'approved':
                print(f"✅ KNOWN visitor: {visitor.get('visitorName')}")
                handle_known_visitor(face_id, visitor)
            else:
                print(f"🚨 UNKNOWN visitor: {face_id}")
                handle_unknown_visitor(face_id, photo_s3_key)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'success': True, 'message': 'Processed all records'})
        }
    
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return {
            'statusCode': 500,
            'body': json.dumps({'success': False, 'error': str(e)})
        }

def check_visitor_in_dynamodb(face_id):
    """Check if visitor exists in DynamoDB."""
    try:
        table = dynamodb.Table(DYNAMODB_TABLE)
        response = table.get_item(Key={'faceId': face_id})
        if 'Item' in response:
            return response['Item']
        return None
    except Exception as e:
        print(f"⚠️ DynamoDB error: {str(e)}")
        return None

def handle_known_visitor(face_id, visitor):
    """Handle approved visitor - grant access."""
    print(f"✅ Access granted to: {visitor.get('visitorName')}")
    
    try:
        sns_client.publish(
            PhoneNumber=OWNER_PHONE,
            Message=f"✅ Approved visitor '{visitor.get('visitorName')}' entering now. FaceId: {face_id}"
        )
    except Exception as e:
        print(f"⚠️ SMS error: {str(e)}")

def handle_unknown_visitor(face_id, photo_s3_key):
    """Handle unknown visitor - notify owner for approval."""
    try:
        # Generate presigned URL for photo (24 hours)
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': photo_s3_key},
            ExpiresIn=86400
        )
        print(f"📷 Presigned URL generated")
        
        # Generate approval link
        approval_link = f"{WEB_BASE_URL}/wp1.html?faceId={face_id}&photoUrl={urlencode({'photoUrl': presigned_url})[8:]}"
        
        # Send EMAIL to owner with photo
        send_email_to_owner(approval_link, presigned_url, face_id)
        print(f"✅ Email sent to owner")
        
        # Send SMS to owner with approval link
        send_sms_to_owner(approval_link, face_id)
        print(f"✅ SMS sent to owner")
        
        # Publish to SNS
        publish_to_sns(approval_link, face_id)
        print(f"✅ Published to SNS")
        
        # Create pending record in DynamoDB
        create_pending_visitor(face_id, photo_s3_key)
        print(f"✅ Pending record created")
    
    except Exception as e:
        print(f"❌ Error handling unknown visitor: {str(e)}")
        import traceback
        print(traceback.format_exc())

def send_email_to_owner(approval_link, photo_url, face_id):
    """Send email to owner with visitor photo and approval link."""
    
    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px;">
            <h2 style="color: #667eea;">🚪 New Visitor Detected</h2>
            
            <p>A visitor has arrived at your door. Please review the photo and approve access.</p>
            
            <h3>Visitor Information:</h3>
            <ul>
                <li><strong>Detection Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</li>
                <li><strong>FaceId:</strong> {face_id}</li>
            </ul>
            
            <h3>Visitor Photo:</h3>
            <img src="{photo_url}" alt="Visitor" style="max-width: 400px; border-radius: 8px; margin: 20px 0;">
            
            <h3>Action Required:</h3>
            <p>
                <a href="{approval_link}" 
                   style="background-color: #667eea; color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; display: inline-block; font-weight: bold;">
                   ✓ Review & Approve Visitor
                </a>
            </p>
            
            <p><strong>Or copy this link:</strong><br/>{approval_link}</p>
            
            <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
            <p style="color: #999; font-size: 12px; text-align: center;">
                Smart Door Authentication System
            </p>
        </body>
    </html>
    """
    
    text_body = f"""
🚪 NEW VISITOR DETECTED

Detection Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
FaceId: {face_id}

REVIEW AND APPROVE HERE:
{approval_link}

Visitor photo is shown in the HTML version of this email.

---
Smart Door Authentication System
    """
    
    ses_client.send_email(
        Source=OWNER_EMAIL,
        Destination={'ToAddresses': [OWNER_EMAIL]},
        Message={
            'Subject': {
                'Data': f'🚪 New Visitor Awaiting Approval [{face_id}]',
                'Charset': 'utf-8'
            },
            'Body': {
                'Text': {'Data': text_body, 'Charset': 'utf-8'},
                'Html': {'Data': html_body, 'Charset': 'utf-8'}
            }
        }
    )

def send_sms_to_owner(approval_link, face_id):
    """Send SMS to owner with approval link."""
    message = f"🚪 New visitor at door!\nApprove: {approval_link}"
    
    sns_client.publish(
        PhoneNumber=OWNER_PHONE,
        Message=message
    )

def publish_to_sns(approval_link, face_id):
    """Publish to SNS topic."""
    message = {
        'faceId': face_id,
        'approvalLink': approval_link,
        'timestamp': datetime.now().isoformat(),
        'event': 'visitor_detected'
    }
    
    sns_client.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject='🚪 New Visitor Detected',
        Message=json.dumps(message, indent=2)
    )

def create_pending_visitor(face_id, photo_s3_key):
    """Create entry in visitors table with pending status"""
    table = dynamodb.Table('visitors')
    table.put_item(
        Item={
            'faceId': face_id,
            'status': 'pending',  # Mark as pending
            'photoS3Key': photo_s3_key,
            'createdAt': int(time.time()),
            'expiresAt': int(time.time()) + (7 * 24 * 60 * 60),  # 7 days
        }
    )

