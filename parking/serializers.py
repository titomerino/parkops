from rest_framework import serializers
from .models import Fee, Entry, Configuration


class FeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fee
        fields = '__all__'


class EntrySerializer(serializers.ModelSerializer):
    fee_description = serializers.StringRelatedField(source='fee', read_only=True)

    class Meta:
        model = Entry
        fields = [
            'id',
            'plate',
            'entry_date_hour',
            'departure_date_hour',
            'fee',
            'fee_description',
            'state'
        ]
        read_only_fields = ('entry_date_hour',)


class ConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Configuration
        fields = '__all__'
