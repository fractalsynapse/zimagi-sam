from django.conf import settings

from settings.config import Config

#
# SAM.gov API
#
SAM_SOURCE_CODE = Config.string('ZIMAGI_SAM_SOURCE_CODE', 'US-SAM')
SAM_API_KEY = Config.string('ZIMAGI_SAM_API_KEY')

#
# Document root path
#
settings.PROJECT_PATH_MAP['sam_document_path'] = 'sam_documents'
