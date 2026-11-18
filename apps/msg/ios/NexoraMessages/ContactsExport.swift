import Contacts
import Foundation

/// The address book for the computer: names, numbers, emails and a small photo (base64 JPEG/PNG thumbnail).
enum ContactsExport {
    static func all(_ done: @escaping (Result<[[String: Any]], Error>) -> Void) {
        let store = CNContactStore()
        store.requestAccess(for: .contacts) { granted, error in
            guard granted else {
                done(.failure(error ?? NSError(domain: "NexoraMessages", code: 1, userInfo: [
                    NSLocalizedDescriptionKey: "Allow Contacts for Nexora Messages in the iPhone's Settings"])))
                return
            }
            DispatchQueue.global(qos: .userInitiated).async {
                let keys: [CNKeyDescriptor] = [
                    CNContactIdentifierKey as CNKeyDescriptor, CNContactGivenNameKey as CNKeyDescriptor,
                    CNContactFamilyNameKey as CNKeyDescriptor, CNContactNicknameKey as CNKeyDescriptor,
                    CNContactOrganizationNameKey as CNKeyDescriptor, CNContactPhoneNumbersKey as CNKeyDescriptor,
                    CNContactEmailAddressesKey as CNKeyDescriptor, CNContactThumbnailImageDataKey as CNKeyDescriptor,
                ]
                var people: [[String: Any]] = []
                do {
                    try store.enumerateContacts(with: CNContactFetchRequest(keysToFetch: keys)) { contact, _ in
                        var name = [contact.givenName, contact.familyName].filter { !$0.isEmpty }.joined(separator: " ")
                        if name.isEmpty { name = contact.nickname.isEmpty ? contact.organizationName : contact.nickname }
                        var person: [String: Any] = [
                            "id": contact.identifier, "name": name, "org": contact.organizationName,
                            "phones": contact.phoneNumbers.map { $0.value.stringValue },
                            "emails": contact.emailAddresses.map { String($0.value) },
                        ]
                        if let photo = contact.thumbnailImageData { person["photo"] = photo.base64EncodedString() }
                        people.append(person)
                    }
                    done(.success(people))
                } catch {
                    done(.failure(error))
                }
            }
        }
    }
}
