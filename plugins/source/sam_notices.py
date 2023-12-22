from systems.plugins.index import BaseProvider
from utility.data import get_identifier, ensure_list, flatten
from utility.sam import SAMAPI
from utility.time import Time


class Provider(BaseProvider('source', 'sam_notices')):

    def load_items(self, context):
        time = Time(date_format = '%m/%d/%Y')
        now = time.now
        now_string = time.to_date_string(now)

        option_names = list(self.meta.get('option', {}).keys())
        option_names.remove('disable_save')

        params = {
            'postedFrom': time.to_date_string(time.shift(now, -364, 'days')),
            'postedTo': now_string,
            'rdlfrom': now_string,
            'rdlto': time.to_date_string(time.shift(now, 364, 'days'))
        }
        for key, value in self.config.items():
            if key in option_names and value:
                params[key] = value

        page_state_id = "{}-{}-page".format(
            self.state_id,
            get_identifier(params)
        )

        def save_offset_index(offset):
            self.command.set_state(page_state_id, offset)

        def delete_offset_index():
            self.command.delete_state(page_state_id)

        for notice in SAMAPI(self.command).load_opportunities(
            params = params,
            offset = self.command.get_state(page_state_id, 0),
            next_callback = save_offset_index,
            complete_callback = delete_offset_index
        ):
            yield notice


    def load_item(self, response, context):
        contacts = []
        documents = []

        notice = {
            'name': response.title,
            'external_id': response.noticeId,
            'solicitation_id': response.solicitationNumber,
            'base_type': response.baseType,
            'type': response.type,
            'description_url': response.descriptionUrl,
            'additional_info_url': response.additionalInfoLink,
            'web_url': response.uiLink,
            'posted_date': response.postedDate,
            'response_deadline': response.responseDeadLine,
            'archive_type': response.archiveType,
            'archive_date': response.archiveDate,
            'setaside_code': response.typeOfSetAside,
            'setaside_name': response.typeOfSetAsideDescription,
            'organization_code': response.fullParentPathCode[1 if len(response.fullParentPathCode) > 1 else 0]
        }
        notice['naics'] = ensure_list(response.naicsCodes) if response.naicsCodes else []
        notice['psc'] = ensure_list(response.classificationCode) if response.classificationCode else []

        notice['office_country'] = response.officeAddress.countryCode if response.officeAddress else None
        notice['office_province'] = response.officeAddress.state if response.officeAddress else None
        notice['office_city'] = response.officeAddress.city if response.officeAddress else None
        notice['office_zipcode'] = response.officeAddress.zipcode if response.officeAddress else None
        notice['location_country'] = response.placeOfPerformance.country.code if response.placeOfPerformance and response.placeOfPerformance.country else None
        notice['location_province'] = response.placeOfPerformance.state.code if response.placeOfPerformance and response.placeOfPerformance.state else None
        notice['location_city'] = response.placeOfPerformance.city.name if response.placeOfPerformance and response.placeOfPerformance.city else None
        notice['location_zipcode'] = response.placeOfPerformance.zip if response.placeOfPerformance else None

        if response.pointOfContact:
            for contact in ensure_list(response.pointOfContact):
                contacts.append({
                    'solicitation_id': response.solicitationNumber,
                    'notice_id': response.noticeId,
                    'name': contact.fullName,
                    'type': contact.type,
                    'title': contact.title,
                    'email': contact.email,
                    'phone': contact.phone,
                    'fax': contact.fax
                })

        if response.resourceLinks:
            for url in ensure_list(response.resourceLinks):
                documents.append({
                    'solicitation_id': response.solicitationNumber,
                    'notice_id': response.noticeId,
                    'url': url
                })
        return {
            'contact': contacts,
            'document': documents,
            'notice': notice
        }
