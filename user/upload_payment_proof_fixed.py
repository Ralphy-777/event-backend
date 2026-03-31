@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_payment_proof(request, booking_id):
    """Upload GCash payment proof"""
    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)
        
        if booking.payment_status == 'paid':
            return Response({'message': 'Payment already confirmed'}, status=status.HTTP_400_BAD_REQUEST)
        
        payment_proof = request.FILES.get('payment_proof')
        gcash_reference = request.data.get('gcash_reference', '').strip()
        
        if not payment_proof:
            return Response({'message': 'Payment proof image is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not gcash_reference:
            return Response({'message': 'GCash Reference Number is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if fields exist before setting
        try:
            booking.payment_proof = payment_proof
            booking.gcash_reference = gcash_reference
        except AttributeError:
            return Response({
                'message': 'Database not updated. Please run: setup_gcash_manual.bat',
                'error': 'Missing payment_proof fields in database'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        booking.payment_status = 'pending_verification'
        booking.save()
        
        return Response({
            'message': 'Payment proof uploaded successfully. Waiting for organizer verification.',
            'booking_id': booking.id
        })
        
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'message': str(e), 'error': 'upload_failed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
