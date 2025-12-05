import json
import boto3
from boto3.dynamodb.conditions import Attr
from decimal import Decimal

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
visitors_table = dynamodb.Table('visitors')

def response(status_code, data):
    """Build HTTP response"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        },
        'body': json.dumps(data, default=str)
    }

def decimal_to_int(obj):
    """Convert Decimal to int for JSON serialization"""
    if isinstance(obj, list):
        return [decimal_to_int(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: decimal_to_int(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj

def lambda_handler(event, context):
    """Get all approved visitors"""
    
    print("=" * 60)
    print("📋 approved-visitors Lambda Started")
    print("=" * 60)
    
    try:
        print("🔍 Scanning for approved visitors...")
        
        # Scan for approved visitors
        response_obj = visitors_table.scan(
            FilterExpression=Attr('status').eq('approved')
        )
        
        approved = response_obj.get('Items', [])
        
        print(f"✅ Found {len(approved)} approved visitors")
        
        # Convert Decimal to proper types
        approved = decimal_to_int(approved)
        
        # Sort by approval time (newest first)
        approved = sorted(approved, key=lambda x: x.get('approvedAt', 0), reverse=True)
        
        # Log each visitor
        for visitor in approved:
            print(f"   - {visitor.get('visitorName')} ({visitor.get('faceId')})")
        
        return response(200, {
            'success': True,
            'visitors': approved,
            'count': len(approved),
            'message': f'Found {len(approved)} approved visitors'
        })
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        print(traceback.format_exc())
        
        return response(500, {
            'success': False,
            'error': str(e),
            'message': 'Error fetching approved visitors'
        })
